from pydantic import BaseModel


class NewSessionRequest(BaseModel):
    title: str | None = None


class ChatRequest(BaseModel):
    session_id: str
    message: str