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
# CORE RAG LOGIC (ported from the updated notebook)
# --------------------------------------------------------------------------

import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from langchain_core.documents import Document

llm = ChatGroq(
    model="qwen/qwen3-32b",
    reasoning_format="hidden",
)

embedding = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)

LINKS_JSON_PATH = "./web-crawller/links_result_deduped.json"

# link-only vectordb: page_content of each doc IS the url string
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

# --- tag extraction prompt/chain (replaces old loose keyword prompt) ---
tags_prompt = PromptTemplate.from_template("""
You are a senior ArduPilot Copter engineer building search queries for a documentation retriever.

Given a junior engineer's question, extract 1-3 keywords/phrases that maximize retrieval accuracy against ArduPilot Copter docs.

Rules:
- Use exact ArduPilot terminology (parameter names like ATC_RAT_RLL_P, mode names like AUTO/LOITER/RTL, component names like EKF3, GPS, compass, ESC).
- Include the specific subsystem/feature (e.g. "geofence", "failsafe", "PID tuning", "motor output").
- Include synonyms only if they map to different doc sections (e.g. "compass calibration" AND "magnetometer calibration").
- Expand acronyms once if the full term aids retrieval (e.g. "EKF" -> also include "Extended Kalman Filter").
- Exclude generic filler words (drone, help, how, issue, problem).
- Order keywords from most specific to most general.
- Output ONLY a JSON array of strings. No explanation, no markdown, no preamble.

Question: {question}

Output:
""")

tags_chain = tags_prompt | llm


def weighted_query(tags):
    weighted = []
    for i, tag in enumerate(tags):
        weight = len(tags) - i  # first tag gets highest repeat count
        weighted.extend([tag] * weight)
    return " ".join(weighted)


def retrieved_question_links(question, decay=0.5):
    """tags -> decayed similarity search against link_retriever -> ranked url docs."""
    tags_msg = tags_chain.invoke(question)
    tags = eval(tags_msg.content) if hasattr(tags_msg, "content") else tags_msg

    scored_docs = {}
    for i, tag in enumerate(tags):
        weight = decay ** i  # 1.0, 0.5, 0.25, ...
        results = link_retriever.vectorstore.similarity_search_with_score(tag, k=5)
        for doc, score in results:
            key = doc.page_content  # the url
            weighted_score = score * (1 / weight) if weight else score
            if key not in scored_docs or weighted_score < scored_docs[key][1]:
                scored_docs[key] = (doc, weighted_score)

    ranked = sorted(scored_docs.values(), key=lambda x: x[1])
    return [doc for doc, _ in ranked]


def _is_valid_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def get_new_urls(retrieved_docs, already_fetched_links):
    seen = set(already_fetched_links)
    final_urls_for_data_loading = []
    for doc in retrieved_docs:
        url = doc.page_content
        # link_retriever's vectordb can contain non-url text (titles, snippets,
        # bad rows in links_result_deduped.json) — skip anything that isn't
        # actually a fetchable http(s) url instead of crashing WebBaseLoader.
        if url and _is_valid_url(url) and url not in seen:
            final_urls_for_data_loading.append(url)
            seen.add(url)
    return final_urls_for_data_loading


already_fetched_links = []
retrieved_links = []  # links from the most recent retrieval (used as "already_visited")

splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)

# empty content vectordb, populated on-demand as pages are scraped.
# `main_retriever` is the SINGLE retriever used for answering (docs' content, not links).
vectordb = Chroma(collection_name="main_docs", embedding_function=embedding)
main_retriever = vectordb.as_retriever()

# --- parameter whitelist retriever (prevents the LLM from inventing param names) ---
PARAMETERS_URL = "https://ardupilot.org/copter/docs/parameters.html"

resp = requests.get(PARAMETERS_URL)
resp.encoding = "utf-8"  # fixes the mojibake from wrong auto-detected encoding
soup = BeautifulSoup(resp.text, "html.parser")
h3_tags = [h3.get_text(strip=True).replace("\u00b6", "").strip() for h3 in soup.find_all("h3")]

param_docs = [Document(page_content=p) for p in h3_tags]
param_vectordb = Chroma.from_documents(param_docs, embedding=embedding)
param_retriever = param_vectordb.as_retriever(search_kwargs={"k": 15})

prompt2 = ChatPromptTemplate.from_messages([
    ("system",
     "Answer the question using the context below.\n\nContext:\n{context}. Links in the answer should strictly from {already_visited}. "
     "Any ArduPilot parameter you mention must come strictly from this list — do not invent or alter parameter names, "
     "and if none of these fit, don't mention a parameter at all:\n{valid_params}"),
    MessagesPlaceholder(variable_name="history"),
    ("human", "{question}")
])


def _run_keyword_and_scrape(question: str):
    """Same steps as the notebook: tags -> retrieve links -> filter new ones ->
    scrape -> split -> add into main_retriever's vectordb."""
    global retrieved_links

    retrieved_links = retrieved_question_links(question=question)

    new_urls = get_new_urls(retrieved_links, already_fetched_links)
    already_fetched_links.extend(new_urls)

    if new_urls:
        docs = WebBaseLoader(new_urls).load()
        splitted_docs = splitter.split_documents(docs)
        if splitted_docs:
            vectordb.add_documents(splitted_docs)


chain = (
    {
        "context": lambda x: main_retriever.invoke(x["question"]),
        "question": lambda x: x["question"],
        "history": lambda x: x["history"],
        "already_visited": lambda x: list(retrieved_links),
        "valid_params": lambda x: param_retriever.invoke(x["question"]),
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
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)