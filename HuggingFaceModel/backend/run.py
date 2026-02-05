#!/usr/bin/env python
"""
Run Script for Resume Matching System
Handles proper Python path setup
"""

import sys
import os
from pathlib import Path

# Add parent directory to Python path
backend_dir = Path(__file__).parent
project_dir = backend_dir.parent
sys.path.insert(0, str(project_dir))

print(f"[SETUP] Backend dir: {backend_dir}")
print(f"[SETUP] Project dir: {project_dir}")
print(f"[SETUP] Python path: {sys.path[:3]}")

if __name__ == "__main__":
    import uvicorn
    
    # Check which app to run
    if len(sys.argv) > 1 and sys.argv[1] == "agent":
        print("\n[STARTING] Agent Executor on http://localhost:8001")
        print("[INFO] For natural language queries via Groq\n")
        uvicorn.run(
            "backend.main:app",
            host="0.0.0.0",
            port=8001,
            reload=True
        )
    else:
        print("\n[STARTING] Main API on http://localhost:8000")
        print("[INFO] For direct API endpoints\n")
        uvicorn.run(
            "backend.app:app",
            host="0.0.0.0",
            port=8000,
            reload=True
        )
