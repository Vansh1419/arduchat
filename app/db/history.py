from datetime import datetime

from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.chat_history import BaseChatMessageHistory
from langchain_community.vectorstores import Chroma

from app.core.llm import embedding
from app.db.database import get_conn

# small separate vectordb+retriever used only to store/search past
# messages for a session (kept apart from main_retriever, as requested)
history_vector_db = Chroma(collection_name="chat_history", embedding_function=embedding)


def save_message(session_id: str, role: str, content: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (session_id, role, content, datetime.utcnow().isoformat()),
        )
        conn.commit()
    try:
        history_vector_db.add_documents([
            Document(page_content=content, metadata={"session_id": session_id, "role": role})
        ])
    except Exception:
        pass


def load_history_messages(session_id: str):
    with get_conn() as conn:
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
        rows = load_history_messages(self.session_id)
        msgs = []
        for role, content in rows:
            if role == "human":
                msgs.append(HumanMessage(content=content))
            else:
                msgs.append(AIMessage(content=content))
        return msgs

    def add_message(self, message) -> None:
        role = "human" if isinstance(message, HumanMessage) else "ai"
        save_message(self.session_id, role, message.content)

    def clear(self) -> None:
        with get_conn() as conn:
            conn.execute("DELETE FROM messages WHERE session_id = ?", (self.session_id,))
            conn.commit()


def get_session_history(session_id: str):
    return SQLiteChatMessageHistory(session_id)