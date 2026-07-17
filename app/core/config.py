import os
from dotenv import load_dotenv

load_dotenv()

os.environ["HF_TOKEN"] = os.getenv("HF_TOKEN", "")
os.environ["GROQ_API_KEY"] = os.getenv("GROQ_API_KEY", "")

LINKS_JSON_PATH = "./app/links/links_result_deduped.json"
PARAMETERS_URL = "https://ardupilot.org/copter/docs/parameters.html"
DB_PATH = os.getenv("CHAT_DB_PATH", "chat_history.db")

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
LLM_MODEL = "qwen/qwen3-32b"