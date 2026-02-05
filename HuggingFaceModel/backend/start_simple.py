"""
Simplified Combined Server - WITHOUT Agent (to avoid LangChain issues)
All endpoints on port 8000
"""

import os
import sys
from pathlib import Path

# Set environment variables
os.environ["GROQ_API_KEY"] = ""
os.environ["AWS_REGION"] = "us-east-1"
os.environ["PG_DB"] = "resumes"
os.environ["PG_USER"] = ""
os.environ["PG_PASS"] = ""
os.environ["PG_HOST"] = ""
os.environ["PG_PORT"] = "5432"

print("✅ Environment variables set")

# Fix imports
backend_dir = Path(__file__).parent
project_dir = backend_dir.parent
sys.path.insert(0, str(project_dir))

# Import main app only (skip agent for now)
try:
    from backend.app import app
except:
    from app import app

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Add simple agent endpoint directly
from pydantic import BaseModel

class AgentQuery(BaseModel):
    query: str

@app.post("/agent/agent_query")
async def agent_query_simple(request: AgentQuery):
    """
    Simple agent endpoint without LangChain
    Just routes to search for now
    """
    try:
        # Import search function
        from backend.vectorstore.resume_store import query_resumes
        
        # Search resumes
        results = query_resumes(request.query, top_k=10)
        
        return {
            "status": "success",
            "query": request.query,
            "results": results,
            "message": "Searched resumes (agent functionality simplified)"
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "message": "Error searching resumes"
        }

@app.get("/")
async def root():
    return {
        "message": "Resume Matching API - Simplified Combined Server",
        "status": "online",
        "endpoints": {
            "upload": "POST /upload",
            "search": "POST /search/search_resume", 
            "agent": "POST /agent/agent_query (simplified)"
        }
    }

if __name__ == "__main__":
    import uvicorn
    
    print("\n🚀 Starting Simplified Server on http://localhost:8000")
    print("📡 All endpoints available (agent simplified)")
    print("✅ No LangChain dependencies!\n")
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        reload=True
    )
