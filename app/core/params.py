import requests
from bs4 import BeautifulSoup
from langchain_core.documents import Document
from langchain_community.vectorstores import Chroma

from app.core.llm import embedding
from app.core.config import PARAMETERS_URL


def _build_param_retriever():
    resp = requests.get(PARAMETERS_URL)
    resp.encoding = "utf-8"  # fixes mojibake from wrong auto-detected encoding
    soup = BeautifulSoup(resp.text, "html.parser")
    h3_tags = [
        h3.get_text(strip=True).replace("\u00b6", "").strip()
        for h3 in soup.find_all("h3")
    ]
    param_docs = [Document(page_content=p) for p in h3_tags]
    param_vectordb = Chroma.from_documents(param_docs, embedding=embedding)
    return param_vectordb.as_retriever(search_kwargs={"k": 15})


param_retriever = _build_param_retriever()