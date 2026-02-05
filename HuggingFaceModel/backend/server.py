"""
Complete Standalone Resume Matching Server
Works without import issues
"""

import os
import sys
from pathlib import Path

# CRITICAL: Fix Python path BEFORE any imports
backend_dir = Path(__file__).parent
project_dir = backend_dir.parent
sys.path.insert(0, str(project_dir))  # Add HuggingFaceModel to path
sys.path.insert(0, str(backend_dir))   # Add backend to path

print(f"[PATH] Added to sys.path: {project_dir}")
print(f"[PATH] Added to sys.path: {backend_dir}")

# Set environment variables
os.environ["GROQ_API_KEY"] = ""
os.environ["PG_DB"] = "resumes"
os.environ["PG_USER"] = ""
os.environ["PG_PASS"] = ""
os.environ["PG_HOST"] = ""
os.environ["PG_PORT"] = "5432"

print("✅ Environment variables set\n")

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import tempfile
import json

# Create app
app = FastAPI(title="Resume Matching API")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# Import modules (AFTER path is fixed)
# ==========================================
print("[IMPORT] Loading modules...")

try:
    from utils.parsing import parse_resume
    print("✅ utils.parsing imported")
except Exception as e:
    print(f"❌ Error importing parsing: {e}")
    parse_resume = None

try:
    from vectorstore.resume_store import add_resume, query_resumes
    print("✅ vectorstore.resume_store imported")
except Exception as e:
    print(f"❌ Error importing resume_store: {e}")
    add_resume = None
    query_resumes = None

try:
    from models.embeddings import embed_text
    print("✅ models.embeddings imported")
except Exception as e:
    print(f"❌ Error importing embeddings: {e}")
    embed_text = None

print()

# ==========================================
# Request Models
# ==========================================
class SearchRequest(BaseModel):
    query: str
    min_years: int = 0
    top_k: int = 10

class AgentRequest(BaseModel):
    query: str

# ==========================================
# Endpoints
# ==========================================

@app.get("/")
async def root():
    return {
        "message": "Resume Matching API - Standalone Server",
        "status": "online",
        "endpoints": {
            "upload": "POST /upload",
            "search": "POST /search/search_resume",
            "agent": "POST /agent/agent_query"
        }
    }

@app.post("/upload")
async def upload_resume(file: UploadFile = File(...)):
    """Upload and parse a resume"""
    
    if parse_resume is None or add_resume is None:
        raise HTTPException(status_code=500, detail="Parsing modules not loaded")
    
    try:
        # Save uploaded file temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename).suffix) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name
        
        print(f"\n[UPLOAD] Processing: {file.filename}")
        
        # Parse resume
        parsed = parse_resume(tmp_path, file.filename)
        
        # Store in database
        result = add_resume(tmp_path, file.filename)
        
        # Cleanup
        os.unlink(tmp_path)
        
        return {
            "status": "success",
            "message": "Resume uploaded and processed",
            "resume_id": result.get('resume_id'),
            "name": result.get('name'),
            "skills_count": result.get('skills_count', 0),
            "experience_skills": result.get('experience_skills', 0),
            "chunks": result.get('chunks', 0)
        }
    
    except Exception as e:
        print(f"[ERROR] Upload failed: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/search/search_resume")
async def search_resumes(request: SearchRequest):
    """Search for matching resumes"""
    
    if query_resumes is None:
        raise HTTPException(status_code=500, detail="Search module not loaded")
    
    try:
        print(f"\n[SEARCH] Query: {request.query[:100]}...")
        
        # Search
        results = query_resumes(
            jd_text=request.query,
            top_k=request.top_k
        )
        
        print(f"[SEARCH] Found {len(results)} candidates")
        
        return {
            "status": "success",
            "query": request.query,
            "results": results,
            "count": len(results)
        }
    
    except Exception as e:
        print(f"[ERROR] Search failed: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/agent/agent_query")
async def agent_query(request: AgentRequest):
    """Simple agent endpoint - routes to search"""
    
    if query_resumes is None:
        raise HTTPException(status_code=500, detail="Search module not loaded")
    
    try:
        print(f"\n[AGENT] Query: {request.query[:100]}...")
        
        # Route to search
        results = query_resumes(
            jd_text=request.query,
            top_k=10
        )
        
        return {
            "status": "success",
            "query": request.query,
            "results": results,
            "agent_note": "Routed to search (simplified agent)"
        }
    
    except Exception as e:
        print(f"[ERROR] Agent query failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/stats")
async def get_stats():
    """Get system statistics"""
    
    try:
        import psycopg2
        
        conn = psycopg2.connect(
            dbname=os.getenv("PG_DB"),
            user=os.getenv("PG_USER"),
            password=os.getenv("PG_PASS"),
            host=os.getenv("PG_HOST"),
            port=os.getenv("PG_PORT")
        )
        
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM resume_data.resume_profiles")
            total_resumes = cur.fetchone()[0]
            
            cur.execute("SELECT COUNT(*) FROM resume_data.resume_embeddings")
            total_embeddings = cur.fetchone()[0]
        
        conn.close()
        
        return {
            "status": "online",
            "total_resumes": total_resumes,
            "total_embeddings": total_embeddings
        }
    
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }

# ==========================================
# Startup
# ==========================================
if __name__ == "__main__":
    import uvicorn
    
    print("\n" + "="*60)
    print("🚀 Starting Resume Matching Server")
    print("="*60)
    print("Port: 8000")
    print("Endpoints: /upload, /search/search_resume, /agent/agent_query")
    print("="*60 + "\n")
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        reload=False  # Disable reload to avoid path issues
    )
