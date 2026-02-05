from fastapi import APIRouter
from langchain_groq import ChatGroq
from langchain.agents import initialize_agent, Tool
import requests
import os, uuid
from backend.vectorstore.resume_store import add_resume, query_resumes  # pgvector functions
from backend.vectorstore.jobs_store import add_job  # pgvector jobs
from backend.models.embed_model import embedding_for
from backend.utils.file_utils import extract_skills
from backend.agents.ingest_agent import add_jd,add_resume,QueryRequest
from pydantic import BaseModel
from langchain.tools import StructuredTool
import asyncio
import base64
agent_router = APIRouter()
UPLOAD_FOLDER = "./uploads/"
API_BASE = "http://localhost:8000"  # update if deployed elsewhere

# -------------------------
# Automatic ingestion of resumes
# -------------------------
def ingest_all_resumes():
    results = []
    for file in os.listdir(UPLOAD_FOLDER):
        file_path = os.path.join(UPLOAD_FOLDER, file)
        if os.path.isfile(file_path):
            # support text, pdf, docx
            ext = file_path.split(".")[-1].lower()
            resume_text = ""
            if ext == "txt":
                with open(file_path, "r", encoding="utf-8") as f:
                    resume_text = f.read()
            elif ext == "pdf":
                import pdfplumber
                with pdfplumber.open(file_path) as pdf:
                    resume_text = "\n".join([p.extract_text() for p in pdf.pages if p.extract_text()])
            elif ext == "docx":
                import docx
                doc = docx.Document(file_path)
                resume_text = "\n".join([p.text for p in doc.paragraphs])
            else:
                continue  # skip unsupported formats

           # resume_emb = embedding_for(resume_text)
            skills = extract_skills(resume_text)
            resume_id = str(uuid.uuid4())
            add_resume(file,skills, resume_text)
            results.append({"file": file, "resume_id": resume_id})
    return results

# -------------------------
# Initialize LLM (Groq API)
# -------------------------
# Make sure to set GROQ_API_KEY in your environment
#   Windows PowerShell:   $env:GROQ_API_KEY="your_api_key_here"
#   Linux/macOS:          export GROQ_API_KEY="your_api_key_here"
#
# Available models (2025 beta):
#   "llama3-70b-8192"  (big, best quality)
#   "llama3-8b-8192"   (smaller, cheaper/faster)
#   "mixtral-8x7b-32768" (Mixture of Experts, very fast)
#
llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    temperature=0,
    api_key=""  # Will automatically pick from env var GROQ_API_KEY
)

# -------------------------
# LangChain Tools (calls FastAPI endpoints)
# -------------------------
# def add_jd_tool(jd_text: str):
#     queryRequest = QueryRequest(query=jd_text)
#     try:
#         add_jd(queryRequest)
#         return queryRequest
#     except Exception as e:
#         return {"error": str(e), "payload": queryRequest}
def add_jd_tool(jd_text: str):
    try:
        #decoded_text = base64.b64decode(jd_text.encode("utf-8")).decode("utf-8")
        payload = {"query": jd_text, "file_path": ""}
        response = requests.post(
            f"{API_BASE}/ingest/add_jd",
            json=payload,
            timeout=120
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {"error": str(e), "jd_text": jd_text}


# async def add_jd_tool_async(jd_text: str):
#    # from backend.agents.ingest_agent import add_jd, QueryRequest
#     req = QueryRequest(query=jd_text, file_path="")
#     return await add_jd(req)

def search_resume_tool(jd_text: str):
    try:
        payload = {"query": jd_text}
        response = requests.post(
            f"{API_BASE}/search/search_resume",
            json=payload,
            timeout=120
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {"error": str(e), "jd_text": jd_text}

def feedback_tool(feedback_json: dict):
    response = requests.post(f"{API_BASE}/feedback/feedback", json=feedback_json)
    return response.json()

def train_tool(epochs: int = 1):
    response = requests.post(f"{API_BASE}/train/train", json={"epochs": epochs})
    return response.json()

# -------------------------
# Input schema for tools
# -------------------------
class JDInput(BaseModel):
    jd_text: str

class FeedbackInput(BaseModel):
    feedback_json: dict

class TrainInput(BaseModel):
    epochs: int = 1

# -------------------------
# Structured Tools
# -------------------------
add_jd_structured = StructuredTool.from_function(
    func=add_jd_tool,
    name="Add JD",
    description="Add a Job Description to the system (calls /ingest/add_jd)",
    args_schema=JDInput
)

search_resume_structured = StructuredTool.from_function(
    func=search_resume_tool,
    name="Search Resume",
    description="Search top matching resumes for a given JD (calls /search/search_resume)",
    args_schema=JDInput
)

# ingest_resumes_structured = StructuredTool.from_function(
#     func=lambda _: ingest_all_resumes(),
#     name="Ingest Resumes",
#     description="Automatically ingest all resumes from uploads folder into pgvector DB"
# )

feedback_structured = StructuredTool.from_function(
    func=feedback_tool,
    name="Feedback",
    description="Provide feedback for JD/resume match (calls /feedback/feedback)",
    args_schema=FeedbackInput
)

train_structured = StructuredTool.from_function(
    func=train_tool,
    name="Train Model",
    description="Fine-tune embedding model using feedback (calls /train/train)",
    args_schema=TrainInput
)

ingest_resumes_tool = Tool(
    name="Ingest Resumes",
    func=lambda _: ingest_all_resumes(),
    description="Automatically ingest all resumes from uploads folder into pgvector DB"
)
# -------------------------
# Replace your tools list
# -------------------------
tools = [
    add_jd_structured,
    search_resume_structured,
    ingest_resumes_tool,
    feedback_structured,
    train_structured,
]
# # -------------------------
# # LangChain Tools (calls FastAPI endpoints)
# # -------------------------
# def add_jd_tool(jd_text: str):
#     response = requests.post(f"{API_BASE}/ingest/add_jd", json={"query": jd_text})
#     return response.json()
#
# def search_resume_tool(jd_text: str):
#     response = requests.post(f"{API_BASE}/search/search_resume", json={"query": jd_text})
#     return response.json()
#
# def feedback_tool(feedback_json: dict):
#     response = requests.post(f"{API_BASE}/feedback/feedback", json=feedback_json)
#     return response.json()
#
# def train_tool(epochs: int = 1):
#     response = requests.post(f"{API_BASE}/train/train", json={"epochs": epochs})
#     return response.json()
#
# tools = [
#     Tool(
#         name="Add JD",
#         func=add_jd_tool,
#         description="Add a Job Description to the system (calls /ingest/add_jd)"
#     ),
#     Tool(
#         name="Search Resume",
#         func=search_resume_tool,
#         description="Search top matching resumes for a given JD (calls /search/search_resume)"
#     ),
#     Tool(
#         name="Ingest Resumes",
#         func=lambda q: ingest_all_resumes(),
#         description="Automatically ingest all resumes from uploads folder into pgvector DB"
#     ),
#     Tool(
#         name="Feedback",
#         func=feedback_tool,
#         description="Provide feedback for JD/resume match (calls /feedback/feedback)"
#     ),
#     Tool(
#         name="Train Model",
#         func=train_tool,
#         description="Fine-tune embedding model using feedback (calls /train/train)"
#     )
# ]
# -------------------------
# Build the Agent
# -------------------------
agent = initialize_agent(tools, llm, agent="structured-chat-zero-shot-react-description", verbose=True)

class AgentQueryRequest(BaseModel):
    query: str

# -------------------------
# API Endpoint
# -------------------------
@agent_router.post("/agent_query")
async def agent_query(req: AgentQueryRequest):
    """
    Accepts natural language queries and executes the appropriate tools automatically.
    Example queries:
    - "Add this JD: [paste JD text here]"
    - "Search resumes for this JD: [paste JD text here]"
    - "Ingest all resumes in uploads folder"
    - "Train embedding model with feedback"
    - "Provide feedback: JD=[text], Resume=[snippet], Label=1"
    """
    #jd_encoded = base64.b64encode(req.query.encode("utf-8")).decode("utf-8")
    result = agent.run(req.query)
    return {"result": result}
