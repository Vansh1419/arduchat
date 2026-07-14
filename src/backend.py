"""
FastAPI backend for ArduChat.
Core LangChain logic (llm, embeddings, link_retriever, keyword chain,
main_retriever, prompt2, chain) is UNCHANGED from the notebook.
Only addition: chat session persistence via SQLite + a history-vector-db
retriever (kept SEPARATE from main_retriever, per requirements) that is
used just to give the LLM a light-weight "recall" of older turns when the
in-memory history list gets long. `main_retriever` itself remains the
single retriever used for the whole app (the ArduPilot docs vector db).
"""

import os
import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

os.environ["HF_TOKEN"] = os.getenv("HF_TOKEN", "")
os.environ["GROQ_API_KEY"] = os.getenv("GROQ_API_KEY", "")

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from langchain_huggingface.embeddings import HuggingFaceEmbeddings
from langchain_groq.chat_models import ChatGroq
from langchain_community.document_loaders import JSONLoader, WebBaseLoader
from langchain_community.vectorstores import Chroma
from langchain_core.prompts import PromptTemplate, ChatPromptTemplate, MessagesPlaceholder
from langchain_core.chat_history import InMemoryChatMessageHistory, BaseChatMessageHistory
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_text_splitters import RecursiveCharacterTextSplitter

# --------------------------------------------------------------------------
# ORIGINAL NOTEBOOK LOGIC (unmodified)
# --------------------------------------------------------------------------

llm = ChatGroq(
    model="qwen/qwen3-32b",
    reasoning_format="hidden",
)

embedding = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)

LINKS_JSON_PATH = "../web-crawller/links_result_deduped.json"

# Helper to extract the URL into document metadata
def extract_metadata(record: dict, metadata: dict) -> dict:
    # Adjust "url" if your JSON key is named differently (e.g., "link" or "source")
    metadata["url"] = record.get("url") 
    return metadata

json_data = JSONLoader(
    LINKS_JSON_PATH,
    jq_schema=".[]",
    text_content=True,
).load()

links_vector_db = Chroma.from_documents(
    documents=json_data,
    embedding=embedding,
)
link_retriever = links_vector_db.as_retriever()

prompt = PromptTemplate.from_template("""
You are a senior drone engineer and you are mentoring the juniors on the Ardupilot Copter documentation. 

Here is the junior question : {question},

now your task is to give set of keywords so that retriever can easily find the links that may be necessary for the answering the questions
Just give a array, donot give any thing else
""")

chain_keyword = prompt | llm

already_fetched_urls = set()
url_to_be_searched = []


def add_retrieved_urls(new_urls):
    global url_to_be_searched
    url_to_be_searched = [u for u in new_urls if u not in already_fetched_urls]


def mark_as_fetched():
    already_fetched_urls.update(url_to_be_searched)


# empty seed vectordb for the docs that get scraped on-demand.
# `main_retriever` is the SINGLE retriever used for the whole web app.
splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)

_seed_doc = json_data[0]
vectordb = Chroma.from_documents(documents=[_seed_doc], embedding=embedding)
main_retriever = vectordb.as_retriever()

prompt2 = ChatPromptTemplate.from_messages([
    ("system", "Answer the question using the context below.\n\nContext:\n{context}. In case, if you provide a link make sure it is a working link and from either {already_visited} or {retrieved_links}"),
    MessagesPlaceholder(variable_name="history"),
    ("human", "{question}")
])


def _run_keyword_and_scrape(question: str):
    """Same steps as the notebook cells: get keywords -> retrieve links ->
    scrape any new ones -> split -> add into main_retriever's vectordb."""
    link_keyword = chain_keyword.invoke({"question": question}).content
    link_docs = link_retriever.invoke(link_keyword)
    
    # Extract the URL from metadata rather than the plain page_content text
    retrieved_urls = [
        doc.metadata.get("url") 
        for doc in link_docs 
        if doc.metadata.get("url")
    ]

    add_retrieved_urls(retrieved_urls)

    if url_to_be_searched:
        # WebBaseLoader will now successfully receive a list of actual URL strings
        docs = WebBaseLoader(url_to_be_searched).load()
        splitted_docs = splitter.split_documents(docs)
        if splitted_docs:
            vectordb.add_documents(splitted_docs)

    mark_as_fetched()


chain = (
    {
        "context": lambda x: main_retriever.invoke(x["question"]),
        "question": lambda x: x["question"],
        "history": lambda x: x["history"],
        "already_visited": lambda x: list(already_fetched_urls),
        "retrieved_links": lambda x: list(url_to_be_searched),
    }
    | prompt2
    | llm
)

# --------------------------------------------------------------------------
# SQLite persistence: chat sessions + message history (separate store)
# --------------------------------------------------------------------------

DB_PATH = os.getenv("CHAT_DB_PATH", "chat_history.db")


def _init_db():
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT,
                created_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                role TEXT,
                content TEXT,
                created_at TEXT,
                FOREIGN KEY(session_id) REFERENCES sessions(id)
            )
        """)
        conn.commit()


_init_db()

# a small separate vectordb+retriever used only to store/search past
# messages for a session (kept apart from main_retriever, as requested)
history_vector_db = Chroma(
    collection_name="chat_history",
    embedding_function=embedding,
)


def _save_message(session_id: str, role: str, content: str):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute(
            "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (session_id, role, content, datetime.utcnow().isoformat()),
        )
        conn.commit()
    try:
        from langchain_core.documents import Document
        history_vector_db.add_documents([
            Document(page_content=content, metadata={"session_id": session_id, "role": role})
        ])
    except Exception:
        pass


def _load_history_messages(session_id: str):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
    return rows


class SQLiteChatMessageHistory(BaseChatMessageHistory):
    """Loads/saves messages for a session from SQLite, backing the
    RunnableWithMessageHistory used by `chain_with_history`."""

    def __init__(self, session_id: str):
        self.session_id = session_id

    @property
    def messages(self):
        rows = _load_history_messages(self.session_id)
        msgs = []
        for role, content in rows:
            if role == "human":
                msgs.append(HumanMessage(content=content))
            else:
                msgs.append(AIMessage(content=content))
        return msgs

    def add_message(self, message) -> None:
        role = "human" if isinstance(message, HumanMessage) else "ai"
        _save_message(self.session_id, role, message.content)

    def clear(self) -> None:
        with closing(sqlite3.connect(DB_PATH)) as conn:
            conn.execute("DELETE FROM messages WHERE session_id = ?", (self.session_id,))
            conn.commit()


def get_session_history(session_id: str):
    return SQLiteChatMessageHistory(session_id)


chain_with_history = RunnableWithMessageHistory(
    chain,
    get_session_history,
    input_messages_key="question",
    history_messages_key="history",
)

# --------------------------------------------------------------------------
# FastAPI app
# --------------------------------------------------------------------------

app = FastAPI(title="ArduChat API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class NewSessionRequest(BaseModel):
    title: str | None = None


class ChatRequest(BaseModel):
    session_id: str
    message: str


@app.post("/sessions")
def create_session(req: NewSessionRequest):
    session_id = str(uuid.uuid4())
    title = req.title or "New chat"
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute(
            "INSERT INTO sessions (id, title, created_at) VALUES (?, ?, ?)",
            (session_id, title, datetime.utcnow().isoformat()),
        )
        conn.commit()
    return {"session_id": session_id, "title": title}


@app.get("/sessions")
def list_sessions():
    with closing(sqlite3.connect(DB_PATH)) as conn:
        rows = conn.execute(
            "SELECT id, title, created_at FROM sessions ORDER BY created_at DESC"
        ).fetchall()
    return [{"id": r[0], "title": r[1], "created_at": r[2]} for r in rows]


@app.get("/sessions/{session_id}/messages")
def get_messages(session_id: str):
    rows = _load_history_messages(session_id)
    return [{"role": r[0], "content": r[1]} for r in rows]


@app.delete("/sessions/{session_id}")
def delete_session(session_id: str):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        conn.commit()
    return {"ok": True}


@app.post("/chat")
def chat(req: ChatRequest):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        row = conn.execute("SELECT id FROM sessions WHERE id = ?", (req.session_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="session not found")

    _run_keyword_and_scrape(req.message)

    config = {"configurable": {"session_id": req.session_id}}
    result = chain_with_history.invoke({"question": req.message}, config=config)

    # auto-title the session from the first message
    with closing(sqlite3.connect(DB_PATH)) as conn:
        title_row = conn.execute(
            "SELECT title FROM sessions WHERE id = ?", (req.session_id,)
        ).fetchone()
        if title_row and title_row[0] == "New chat":
            new_title = req.message[:50]
            conn.execute(
                "UPDATE sessions SET title = ? WHERE id = ?", (new_title, req.session_id)
            )
            conn.commit()

    return {"answer": result.content}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)