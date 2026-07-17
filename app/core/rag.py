from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_community.vectorstores import Chroma
from langchain_community.document_loaders import WebBaseLoader

from app.core.llm import llm, embedding
from app.core.links import retrieved_question_links, get_new_urls
from app.core.params import param_retriever

already_fetched_links: list[str] = []
retrieved_links: list[str] = []  # links from the most recent retrieval

splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)

# empty content vectordb, populated on-demand as pages are scraped.
# `main_retriever` is the SINGLE retriever used for answering (docs' content, not links).
vectordb = Chroma(collection_name="main_docs", embedding_function=embedding)
main_retriever = vectordb.as_retriever()

prompt2 = ChatPromptTemplate.from_messages([
    ("system",
     "Answer the question using the context below.\n\nContext:\n{context}. Links in the answer should strictly from {already_visited}. "
     "Any ArduPilot parameter you mention must come strictly from this list — do not invent or alter parameter names, "
     "and if none of these fit, don't mention a parameter at all:\n{valid_params}"),
    MessagesPlaceholder(variable_name="history"),
    ("human", "{question}")
])


def run_keyword_and_scrape(question: str):
    """tags -> retrieve links -> filter new ones -> scrape -> split ->
    add into main_retriever's vectordb."""
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