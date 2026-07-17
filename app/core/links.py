from urllib.parse import urlparse

from langchain_core.prompts import PromptTemplate
from langchain_community.vectorstores import Chroma
from langchain_community.document_loaders import JSONLoader

from app.core.llm import embedding, llm
from app.core.config import LINKS_JSON_PATH

json_data = JSONLoader(
    LINKS_JSON_PATH,
    jq_schema=".[]",
    text_content=True,
).load()

links_vector_db = Chroma.from_documents(documents=json_data, embedding=embedding)
link_retriever = links_vector_db.as_retriever()

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
        weight = len(tags) - i
        weighted.extend([tag] * weight)
    return " ".join(weighted)


def retrieved_question_links(question, decay=0.5):
    """tags -> decayed similarity search against link_retriever -> ranked url docs."""
    tags_msg = tags_chain.invoke(question)
    tags = eval(tags_msg.content) if hasattr(tags_msg, "content") else tags_msg

    scored_docs = {}
    for i, tag in enumerate(tags):
        weight = decay ** i
        results = link_retriever.vectorstore.similarity_search_with_score(tag, k=5)
        for doc, score in results:
            key = doc.page_content
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
    final_urls = []
    for doc in retrieved_docs:
        url = doc.page_content
        if url and _is_valid_url(url) and url not in seen:
            final_urls.append(url)
            seen.add(url)
    return final_urls