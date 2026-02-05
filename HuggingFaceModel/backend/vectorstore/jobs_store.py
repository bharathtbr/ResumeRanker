"""
Jobs Store - Enhanced for JD storage
"""

import os, uuid
import psycopg2
import psycopg2.extras
from typing import List
from backend.models.embeddings import embed_text

# Config
DB_NAME = os.getenv("PG_DB", "resumes")
DB_USER = os.getenv("PG_USER", "")
DB_PASS = os.getenv("PG_PASS", "")
DB_HOST = os.getenv("PG_HOST", "")
DB_PORT = os.getenv("PG_PORT", "5432")

# DB connection
conn = psycopg2.connect(
    dbname=DB_NAME, user=DB_USER, password=DB_PASS, host=DB_HOST, port=DB_PORT
)
conn.autocommit = True

def add_job(jd_text: str, skills: List[str], embedding: List[float] = None) -> str:
    """Insert a new job description"""
    job_id = str(uuid.uuid4())
    
    if embedding is None:
        embedding = embed_text(jd_text)
    
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO resume_data.jobs (id, jd_text, jd_skills, embedding)
            VALUES (%s, %s, %s::jsonb, %s)
        """, (job_id, jd_text, psycopg2.extras.Json(skills), embedding))
    
    print(f"[DB] ✅ Stored JD: {job_id}")
    
    return job_id


def query_jobs(query: str, top_k: int = 10):
    """Semantic search jobs using pgvector"""
    query_emb = embed_text(query)
    
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT id, jd_text as content, jd_skills as skills,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM resume_data.jobs
            ORDER BY embedding <=> %s::vector
            LIMIT %s;
        """, (query_emb, query_emb, top_k))
        
        results = cur.fetchall()
    
    return [dict(r) for r in results]


def get_all_jobs():
    """Fetch all stored JDs"""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT id, jd_text as content, jd_skills as skills FROM resume_data.jobs;")
        jobs = cur.fetchall()
    
    return [dict(j) for j in jobs]
