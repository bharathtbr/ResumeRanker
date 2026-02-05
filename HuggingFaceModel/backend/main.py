"""
Main entry point for Agent Executor
Runs on port 8001 for natural language agent queries
"""

from fastapi import FastAPI
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware

# Fix imports - use relative imports when running from backend/
try:
    # Try absolute import first (when running from project root)
    from backend.agents.agent_executor import agent_router, ingest_all_resumes
except ModuleNotFoundError:
    # Fall back to relative import (when running from backend/)
    from agents.agent_executor import agent_router, ingest_all_resumes


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    #ingested = ingest_all_resumes()
    #print(f"[Startup] Automatically ingested {len(ingested)} resumes from uploads folder.")
    yield
    # Shutdown
    print("[Shutdown] Cleaning up resources... (if needed)")


app = FastAPI(
    title="Resume Matching Agentic AI - Agent Executor",
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

app.include_router(agent_router, prefix="/agent")

# -------------------------
# Run (only for local dev)
# -------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8001, reload=True)
