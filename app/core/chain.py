from langchain_core.runnables.history import RunnableWithMessageHistory

from app.core.rag import chain
from app.db.history import get_session_history

chain_with_history = RunnableWithMessageHistory(
    chain,
    get_session_history,
    input_messages_key="question",
    history_messages_key="history",
)