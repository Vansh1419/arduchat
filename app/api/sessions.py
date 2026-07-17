import uuid
from datetime import datetime

from fastapi import APIRouter

from app.db.database import get_conn
from app.db.schemas import NewSessionRequest
from app.db.history import load_history_messages

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("")
def create_session(req: NewSessionRequest):
    session_id = str(uuid.uuid4())
    title = req.title or "New chat"
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO sessions (id, title, created_at) VALUES (?, ?, ?)",
            (session_id, title, datetime.utcnow().isoformat()),
        )
        conn.commit()
    return {"session_id": session_id, "title": title}


@router.get("")
def list_sessions():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, title, created_at FROM sessions ORDER BY created_at DESC"
        ).fetchall()
    return [{"id": r[0], "title": r[1], "created_at": r[2]} for r in rows]


@router.get("/{session_id}/messages")
def get_messages(session_id: str):
    rows = load_history_messages(session_id)
    return [{"role": r[0], "content": r[1]} for r in rows]


@router.delete("/{session_id}")
def delete_session(session_id: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        conn.execute(
            "DELETE FROM messages WHERE session_id = ?", (session_id,))
        conn.commit()
    return {"ok": True}
