"""
Combined Server - All endpoints on port 8000
No need for separate agent server
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

# Import both apps
try:
    from backend.app import app as main_app
    from backend.main import app as agent_app
except:
    from app import app as main_app
    from main import app as agent_app

# Combine into one
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Create combined app
combined_app = FastAPI(title="Resume Matching - Combined API")

# CORS
combined_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount main app routes
for route in main_app.routes:
    combined_app.routes.append(route)

# Mount agent routes under /agent prefix
for route in agent_app.routes:
    if route.path == "/":
        continue  # Skip duplicate root
    route.path = "/agent" + route.path
    combined_app.routes.append(route)

@combined_app.get("/")
async def root():
    return {
        "message": "Resume Matching API - Combined Server",
        "status": "online",
        "endpoints": {
            "upload": "POST /upload",
            "search": "POST /search/search_resume", 
            "agent": "POST /agent/agent_query"
        }
    }

if __name__ == "__main__":
    import uvicorn
    
    print("\n🚀 Starting Combined Server on http://localhost:8000")
    print("📡 All endpoints (main + agent) available")
    print("✅ No need for separate agent server!\n")
    
    uvicorn.run(
        combined_app,
        host="0.0.0.0",
        port=8000,
        reload=True
    )
