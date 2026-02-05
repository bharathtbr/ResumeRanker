"""
Ingest Agent - Enhanced with Your Parsing Logic
Uses Claude for skill extraction + HuggingFace for embeddings
"""

from fastapi import APIRouter, UploadFile, File
from pydantic import BaseModel
import os, uuid, tempfile
from backend.models.embeddings import embed_text
from backend.utils.parsing import parse_resume, extract_full_skills
from backend.vectorstore.resume_store import add_resume
from backend.vectorstore.jobs_store import add_job

ingest_router = APIRouter()

class QueryRequest(BaseModel):
    query: str
    file_path: str = None

@ingest_router.post("/add_jd")
async def add_jd(req: QueryRequest):
    """Add Job Description"""
    jd_text = req.query.strip()
    if not jd_text:
        return {"status": "empty JD"}
    
    # Extract skills from JD using Claude
    jd_skills_data = extract_full_skills(jd_text, "jd_temp")
    jd_skills = jd_skills_data.get("skills_flat_unique", [])
    
    # Generate embedding
    jd_emb = embed_text(jd_text)
    
    # Store in jobs table
    job_id = add_job(jd_text, jd_skills, jd_emb)
    
    return {
        "status": "JD added",
        "job_id": job_id,
        "skills_extracted": len(jd_skills),
        "skills": jd_skills
    }

@ingest_router.post("/add_resume")
async def add_resume_path(req: QueryRequest):
    """Add resume from file path"""
    if not req.file_path or not os.path.exists(req.file_path):
        return {"status": "file not found"}
    
    filename = os.path.basename(req.file_path)
    
    # Use your parsing logic
    result = add_resume(req.file_path, filename)
    
    return {
        "status": "resume added",
        **result
    }

@ingest_router.post("/upload_resume")
async def upload_resume(file: UploadFile = File(...)):
    """Upload and process resume file"""
    
    # Save uploaded file temporarily
    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name
    
    try:
        # Process using your parsing logic
        result = add_resume(tmp_path, file.filename)
        
        return {
            "status": "resume uploaded and processed",
            **result
        }
    
    finally:
        # Cleanup
        try:
            os.unlink(tmp_path)
        except:
            pass
