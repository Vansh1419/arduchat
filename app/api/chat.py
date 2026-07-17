from fastapi import APIRouter, HTTPException

from app.db.database import get_conn
from app.db.schemas import ChatRequest
from app.core.rag import run_keyword_and_scrape
from app.core.chain import chain_with_history

router = APIRouter(tags=["chat"])


@router.post("/chat")
def chat(req: ChatRequest):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM sessions WHERE id = ?", (req.session_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="session not found")

    run_keyword_and_scrape(req.message)

    config = {"configurable": {"session_id": req.session_id}}
    result = chain_with_history.invoke({"question": req.message}, config=config)

    with get_conn() as conn:
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