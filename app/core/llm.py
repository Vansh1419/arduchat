from langchain_groq.chat_models import ChatGroq
from langchain_huggingface.embeddings import HuggingFaceEmbeddings

from app.core.config import LLM_MODEL, EMBEDDING_MODEL

llm = ChatGroq(model=LLM_MODEL, reasoning_format="hidden")

embedding = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)