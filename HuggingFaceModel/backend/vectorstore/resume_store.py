"""
Enhanced Resume Store with Your Parsing Logic + HuggingFace Embeddings
Replaces simple regex extraction with Claude-based skill extraction
"""

import os, uuid
import psycopg2
import psycopg2.extras
from typing import List, Dict

# Import your parsing logic
from backend.utils.parsing import parse_resume, canonical_resume_id
from backend.models.embeddings import get_embedding_model

# =========================
# Config
# =========================
DB_NAME = os.getenv("PG_DB", "resumes")
DB_USER = os.getenv("PG_USER", "")
DB_PASS = os.getenv("PG_PASS", "")
DB_HOST = os.getenv("PG_HOST", "")
DB_PORT = os.getenv("PG_PORT", "5432")

# =========================
# DB connection
# =========================
conn = psycopg2.connect(
    dbname=DB_NAME, user=DB_USER, password=DB_PASS, host=DB_HOST, port=DB_PORT
)
conn.autocommit = True

# Embedding Model
embed_model = get_embedding_model()

# =========================
# Database Operations
# =========================
def add_resume(file_path: str, filename: str) -> Dict:
    """
    Ingest resume using your parsing logic + HuggingFace embeddings
    
    Flow:
    1. Parse resume (Claude skill extraction)
    2. Store profile in resume_profiles
    3. Store chunks in resume_chunks
    4. Generate embeddings for chunks
    5. Store embeddings in resume_embeddings
    """
    
    print(f"\n[ADD_RESUME] Processing: {filename}")
    
    # Parse resume using your logic
    parsed = parse_resume(file_path, filename)
    
    resume_id = parsed["resume_id"]
    skills_data = parsed["skills_data"]
    skill_experience = parsed["skill_experience"]
    chunks = parsed["chunks"]
    full_text = parsed["full_text"]
    
    # Prepare data for database
    skills_flat = skills_data.get("skills_flat_unique", [])
    skills_hash = hash(tuple(sorted(skills_flat)))
    
    years_exp = 0
    try:
        import re
        m = re.search(r"\d+", str(skills_data.get("years_exp", "0")))
        years_exp = int(m.group()) if m else 0
    except:
        years_exp = 0
    
    # 1. Store profile
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO resume_data.resume_profiles(
                resume_id, file_name, s3_key, s3_uri,
                name, email, phone, location, linkedin_url, title, years_exp,
                summary_one_line, skills_json, skills_flat, skills_hash,
                skill_experience_json, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s,
                %s::jsonb, now()
            )
            ON CONFLICT (resume_id) DO UPDATE SET
                file_name=EXCLUDED.file_name,
                name=EXCLUDED.name,
                email=EXCLUDED.email,
                phone=EXCLUDED.phone,
                location=EXCLUDED.location,
                linkedin_url=EXCLUDED.linkedin_url,
                title=EXCLUDED.title,
                years_exp=EXCLUDED.years_exp,
                summary_one_line=EXCLUDED.summary_one_line,
                skills_json=EXCLUDED.skills_json,
                skills_flat=EXCLUDED.skills_flat,
                skills_hash=EXCLUDED.skills_hash,
                skill_experience_json=EXCLUDED.skill_experience_json,
                updated_at=now();
        """, (
            resume_id, filename, filename, f"file://{file_path}",
            skills_data.get("name", ""),
            skills_data.get("email", ""),
            skills_data.get("phone", ""),
            skills_data.get("location", ""),
            skills_data.get("linkedin_url", ""),
            skills_data.get("title", ""),
            years_exp,
            skills_data.get("summary_one_line", ""),
            psycopg2.extras.Json(skills_data),
            skills_flat,
            str(skills_hash),
            psycopg2.extras.Json(skill_experience)
        ))
    
    print(f"[DB] ✅ Stored profile: {resume_id}")
    
    # 2. Store chunks and embeddings
    for idx, chunk in enumerate(chunks):
        chunk_id = str(uuid.uuid4())
        vector_key = f"{resume_id}_p1_c{idx}"
        
        # Store chunk
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO resume_data.resume_chunks(
                    id, resume_id, vector_key, page, chunk_index, chunk_text
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (vector_key) DO UPDATE SET chunk_text=EXCLUDED.chunk_text
            """, (chunk_id, resume_id, vector_key, 1, idx, chunk))
        
        # Generate embedding
        embedding = embed_model.encode(chunk)
        
        # Store embedding
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO resume_data.resume_embeddings(
                    resume_id, chunk_id, embedding
                ) VALUES (%s, %s, %s)
                ON CONFLICT (chunk_id) DO UPDATE SET embedding=EXCLUDED.embedding
            """, (resume_id, chunk_id, embedding))
    
    print(f"[DB] ✅ Stored {len(chunks)} chunks + embeddings")
    
    return {
        "resume_id": resume_id,
        "filename": filename,
        "name": skills_data.get("name"),
        "skills_count": len(skills_flat),
        "experience_skills": len(skill_experience),
        "chunks": len(chunks)
    }


def query_resumes(query: str, top_k: int = 10) -> List[Dict]:
    """
    Search resumes using pgvector semantic similarity
    """
    
    print(f"[QUERY] Searching for: {query[:100]}...")
    
    # Generate query embedding
    query_emb = embed_model.encode(query)
    
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        # Search using pgvector cosine distance
        cur.execute("""
            SELECT 
                rp.resume_id,
                rp.name,
                rp.file_name as filename,
                rp.title,
                rp.years_exp,
                rp.email,
                rp.skills_flat,
                rp.skill_experience_json,
                AVG(1 - (re.embedding <=> %s::vector)) as similarity
            FROM resume_data.resume_embeddings re
            JOIN resume_data.resume_profiles rp ON re.resume_id = rp.resume_id
            GROUP BY rp.resume_id, rp.name, rp.file_name, rp.title, 
                     rp.years_exp, rp.email, rp.skills_flat, rp.skill_experience_json
            ORDER BY similarity DESC
            LIMIT %s;
        """, (query_emb, top_k))
        
        results = cur.fetchall()
    
    print(f"[QUERY] Found {len(results)} resumes")
    
    # Convert to dicts and format
    formatted_results = []
    for r in results:
        formatted_results.append({
            "resume_id": r["resume_id"],
            "name": r["name"],
            "filename": r["filename"],
            "title": r["title"],
            "years_exp": r["years_exp"],
            "email": r["email"],
            "skills": ", ".join(r["skills_flat"]) if r["skills_flat"] else "",
            "skill_experience": r["skill_experience_json"],
            "similarity": float(r["similarity"])
        })
    
    return formatted_results


def get_all_resumes() -> List[Dict]:
    """Fetch all stored resumes"""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT 
                resume_id, name, file_name as filename, 
                title, years_exp, email, skills_flat
            FROM resume_data.resume_profiles
            ORDER BY updated_at DESC;
        """)
        resumes = cur.fetchall()
    
    return [dict(r) for r in resumes]


def get_resume_by_id(resume_id: str) -> Dict:
    """Get resume profile by ID"""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT * FROM resume_data.resume_profiles
            WHERE resume_id = %s;
        """, (resume_id,))
        resume = cur.fetchone()
    
    return dict(resume) if resume else None
