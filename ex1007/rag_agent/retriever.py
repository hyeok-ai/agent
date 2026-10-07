from pathlib import Path

from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
from langchain_core.tools import create_retriever_tool
from dotenv import load_dotenv

load_dotenv()

# 실행 위치(cwd)와 무관하게 이 스크립트가 있는 폴더 기준으로 경로 고정
DB_PATH = str(Path(__file__).resolve().parent / "chroma_db")

vectorstore = Chroma(
    persist_directory=DB_PATH,
    embedding_function=OpenAIEmbeddings(model="text-embedding-3-small"),
    collection_name="korean_pdf"
)

vectorstore.get()

retriever = vectorstore.as_retriever(search_kwargs={"k": 3})

retriever_tool = create_retriever_tool(
    retriever,
    name="pdf_search",
    description="use this tool to search information from the Korean Spelling Rules PDF document",
)

if __name__ == "__main__":
    response = retriever_tool.invoke("부엌 이 들어간 경우 어떻게 발음하나요?")
    print(response)