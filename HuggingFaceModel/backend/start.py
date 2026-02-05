"""
Simple startup script for PyCharm
Just click Run in PyCharm!
"""

import os

# Set environment variables
os.environ["GROQ_API_KEY"] = ""
os.environ["AWS_REGION"] = "us-east-1"
os.environ["PG_DB"] = "resumes"
os.environ["PG_USER"] = ""
os.environ["PG_PASS"] = ""
os.environ["PG_HOST"] = ""
os.environ["PG_PORT"] = "5432"

print("✅ Environment variables set")
print("🚀 Starting server...")

# Run the app
import sys
from pathlib import Path

# Fix imports
backend_dir = Path(__file__).parent
project_dir = backend_dir.parent
sys.path.insert(0, str(project_dir))

# Start server
import uvicorn

if __name__ == "__main__":
    # Check if agent mode
    agent_mode = len(sys.argv) > 1 and sys.argv[1] == "agent"
    
    if agent_mode:
        print("\n🤖 Starting Agent Executor on http://localhost:8001")
        print("📝 For natural language queries\n")
        uvicorn.run(
            "backend.main:app",
            host="0.0.0.0",
            port=8001,
            reload=True
        )
    else:
        print("\n🌐 Starting Main API on http://localhost:8000")
        print("📡 For direct endpoints\n")
        uvicorn.run(
            "backend.app:app",
            host="0.0.0.0",
            port=8000,
            reload=True
        )
