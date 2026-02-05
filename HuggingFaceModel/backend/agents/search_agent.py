"""
Search Agent - Enhanced with HuggingFace Scoring
Multi-metric scoring using embeddings + skill experience
"""

from fastapi import APIRouter
from pydantic import BaseModel
from backend.models.embeddings import embed_text
from backend.utils.parsing import extract_full_skills
from backend.utils.scoring import compute_final_score
from backend.vectorstore.resume_store import query_resumes, get_resume_by_id
import psycopg2
import psycopg2.extras
import os

search_router = APIRouter()

DB_NAME = os.getenv("PG_DB", "resumes")
DB_USER = os.getenv("PG_USER", "")
DB_PASS = os.getenv("PG_PASS", "")
DB_HOST = os.getenv("PG_HOST", "")
DB_PORT = os.getenv("PG_PORT", "5432")

def pg_conn():
    return psycopg2.connect(
        dbname=DB_NAME, user=DB_USER, password=DB_PASS, host=DB_HOST, port=DB_PORT
    )

class SearchRequest(BaseModel):
    query: str
    min_years: int = 0
    top_k: int = 10

@search_router.post("/search_resume")
async def search_resume(req: SearchRequest):
    """
    Search resumes with enhanced scoring
    
    Uses:
    1. pgvector similarity
    2. HuggingFace semantic similarity
    3. Skill overlap from skill_experience_json
    4. Experience matching
    """
    
    jd_text = req.query.strip()
    if not jd_text:
        return {"status": "empty query"}
    
    # Extract skills from JD using Claude
    jd_skills_data = extract_full_skills(jd_text, "jd_search")
    jd_skills = jd_skills_data.get("skills_flat_unique", [])
    
    print(f"[SEARCH] JD skills: {jd_skills}")
    
    # Get top candidates from pgvector
    resumes = query_resumes(jd_text, top_k=req.top_k * 2)  # Get 2x for re-ranking
    
    # Get full text for each resume
    def get_resume_full_text(resume_id: str) -> str:
        with pg_conn() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT chunk_text
                FROM resume_data.resume_chunks
                WHERE resume_id = %s
                ORDER BY page, chunk_index
            """, (resume_id,))
            chunks = cur.fetchall()
        return "\n".join([chunk[0] for chunk in chunks if chunk[0]])
    
    # Score each resume
    hits = []
    for r in resumes:
        resume_id = r["resume_id"]
        resume_full_text = get_resume_full_text(resume_id)
        resume_skills = r["skills"].split(",") if r["skills"] else []
        resume_skills = [s.strip() for s in resume_skills if s.strip()]
        resume_skill_exp = r.get("skill_experience", {}) or {}
        
        # Compute multi-metric score
        score_dict = compute_final_score(
            jd_text=jd_text,
            jd_skills=jd_skills,
            jd_years=req.min_years,
            resume_text=resume_full_text[:5000],  # Limit for efficiency
            resume_skills=resume_skills,
            resume_skill_exp=resume_skill_exp,
            pgvector_similarity=r.get("similarity", 0.0)
        )
        
        hits.append({
            "resume_id": resume_id,
            "name": r.get("name", ""),
            "filename": r.get("filename", ""),
            "title": r.get("title", ""),
            "years_exp": r.get("years_exp", 0),
            "email": r.get("email", ""),
            **score_dict
        })
    
    # Sort by final score
    hits = sorted(hits, key=lambda x: x["score"], reverse=True)
    
    # Take top K
    hits = hits[:req.top_k]
    
    return {
        "jd_skills": jd_skills,
        "results": hits,
        "total_candidates": len(resumes)
    }
