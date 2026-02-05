"""
Main FastAPI Application
Runs on port 8000 for direct API endpoints
"""

from fastapi import FastAPI
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware

# Fix imports
try:
    # Try absolute import first (when running from project root)
    from backend.agents.ingest_agent import ingest_router
    from backend.agents.search_agent import search_router
    from backend.agents.feedback_agent import feedback_router
    from backend.agents.train_agent import train_router
except ModuleNotFoundError:
    # Fall back to relative import (when running from backend/)
    from agents.ingest_agent import ingest_router
    from agents.search_agent import search_router
    from agents.feedback_agent import feedback_router
    from agents.train_agent import train_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("[Startup] Resume Matching API starting...")
    yield
    # Shutdown
    print("[Shutdown] Cleaning up resources...")


app = FastAPI(
    title="Resume Matching API",
    description="Enhanced with Claude Parsing + HuggingFace Embeddings",
    version="2.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production!
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include all routers
app.include_router(ingest_router, prefix="/ingest", tags=["Ingest"])
app.include_router(search_router, prefix="/search", tags=["Search"])
app.include_router(feedback_router, prefix="/feedback", tags=["Feedback"])
app.include_router(train_router, prefix="/train", tags=["Train"])

@app.get("/")
async def root():
    return {
        "message": "Resume Matching API - Enhanced Version",
        "endpoints": {
            "ingest": "/ingest (add resumes/JDs)",
            "search": "/search (find candidates)",
            "feedback": "/feedback (provide ratings)",
            "train": "/train (fine-tune models)"
        },
        "docs": "/docs"
    }

# -------------------------
# Run (only for local dev)
# -------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app:app", host="0.0.0.0", port=8000, reload=True)
