"""
Complete Testing Script - Using Groq + HuggingFace (NO AWS)
Run this in PyCharm to test parsing, scoring, and search
"""

import sys
import os
from pathlib import Path

# Add parent to path
backend_dir = Path(__file__).parent
project_dir = backend_dir.parent
sys.path.insert(0, str(project_dir))

print("="*80)
print("RESUME MATCHING SYSTEM - COMPLETE TEST (Groq + HuggingFace)")
print("="*80)

# Test 1: Check Dependencies
print("\n[TEST 1] Checking Dependencies...")
try:
    from groq import Groq
    print("✅ groq installed")
except ImportError:
    print("❌ groq NOT installed - run: pip install groq")

try:
    from sentence_transformers import SentenceTransformer
    print("✅ sentence-transformers installed")
except ImportError:
    print("❌ sentence-transformers NOT installed - run: pip install sentence-transformers")

try:
    import psycopg2
    print("✅ psycopg2 installed")
except ImportError:
    print("❌ psycopg2 NOT installed - run: pip install psycopg2-binary")

try:
    from PyPDF2 import PdfReader
    print("✅ PyPDF2 installed")
except ImportError:
    print("❌ PyPDF2 NOT installed - run: pip install PyPDF2")

# Test 2: Database Connection
print("\n[TEST 2] Testing Database Connection...")
try:
    import psycopg2
    conn = psycopg2.connect(
        dbname=os.getenv("PG_DB", "resumes"),
        user=os.getenv("PG_USER", ""),
        password=os.getenv("PG_PASS", ""),
        host=os.getenv("PG_HOST", ""),
        port=os.getenv("PG_PORT", "5432")
    )
    print("✅ Database connection successful")
    
    # Check tables
    with conn.cursor() as cur:
        cur.execute("""
            SELECT table_name FROM information_schema.tables 
            WHERE table_schema = 'resume_data'
        """)
        tables = [row[0] for row in cur.fetchall()]
        print(f"✅ Found {len(tables)} tables: {tables}")
    
    conn.close()
except Exception as e:
    print(f"❌ Database connection failed: {e}")

# Test 3: Groq Connection
print("\n[TEST 3] Testing Groq Connection...")
try:
    from groq import Groq
    
    groq_key = os.getenv("GROQ_API_KEY", "")
    groq_client = Groq(api_key=groq_key)
    
    # Test a simple call
    print("   Testing Groq API...")
    response = groq_client.chat.completions.create(
        messages=[{"role": "user", "content": "Say hello"}],
        model="llama-3.3-70b-versatile",
        max_tokens=10
    )
    print(f"✅ Groq connected: {response.choices[0].message.content}")
    
except Exception as e:
    print(f"❌ Groq connection failed: {e}")
    print("   Make sure GROQ_API_KEY is set")

# Test 4: HuggingFace Embeddings
print("\n[TEST 4] Testing HuggingFace Embeddings...")
try:
    from backend.models.embed_model import embedding_for
    
    print("   Loading model (this may take a minute first time)...")
    
    # Test embedding
    text = "Python developer with 5 years experience"
    embedding = embedding_for(text)
    print(f"✅ Generated embedding: {len(embedding)} dims")
    print(f"   Sample values: {embedding[:5]}")
    
except Exception as e:
    print(f"❌ Embedding test failed: {e}")
    import traceback
    traceback.print_exc()

# Test 5: Resume Parsing
print("\n[TEST 5] Testing Resume Parsing (with Groq)...")
try:
    from backend.utils.parsing import parse_resume
    
    # Find a test resume
    uploads_dir = backend_dir / "uploads"
    resumes = list(uploads_dir.glob("*.pdf")) + list(uploads_dir.glob("*.docx"))
    
    if not resumes:
        print("❌ No resumes found in uploads/ folder")
        print("   Please add a resume to test")
    else:
        test_resume = resumes[0]
        print(f"   Testing with: {test_resume.name}")
        
        result = parse_resume(str(test_resume), test_resume.name)
        
        print(f"✅ Resume parsed successfully")
        print(f"   Resume ID: {result['resume_id']}")
        print(f"   Name: {result['skills_data'].get('name')}")
        print(f"   Email: {result['skills_data'].get('email')}")
        print(f"   Skills extracted: {len(result['skills_data'].get('skills_flat_unique', []))}")
        print(f"   Experience skills: {len(result['skill_experience'])}")
        print(f"   Chunks created: {len(result['chunks'])}")
        
        # Show sample skills
        skills = result['skills_data'].get('skills_flat_unique', [])[:10]
        print(f"   Sample skills: {skills}")
        
        # Show sample experience
        if result['skill_experience']:
            skill_name = list(result['skill_experience'].keys())[0]
            skill_exp = result['skill_experience'][skill_name]
            print(f"   Sample experience ({skill_name}): {skill_exp.get('total_years')}y")

except Exception as e:
    print(f"❌ Parsing test failed: {e}")
    import traceback
    traceback.print_exc()

# Test 6: Resume Storage
print("\n[TEST 6] Testing Resume Storage...")
try:
    from backend.vectorstore.resume_store import add_resume
    
    uploads_dir = backend_dir / "uploads"
    resumes = list(uploads_dir.glob("*.pdf")) + list(uploads_dir.glob("*.docx"))
    
    if resumes:
        test_resume = resumes[0]
        print(f"   Storing: {test_resume.name}")
        
        result = add_resume(str(test_resume), test_resume.name)
        
        print(f"✅ Resume stored successfully")
        print(f"   Resume ID: {result['resume_id']}")
        print(f"   Name: {result['name']}")
        print(f"   Skills: {result['skills_count']}")
        print(f"   Experience skills: {result['experience_skills']}")
        print(f"   Chunks: {result['chunks']}")
    else:
        print("⚠️  No resumes to test storage")
        
except Exception as e:
    print(f"❌ Storage test failed: {e}")
    import traceback
    traceback.print_exc()

# Test 7: Search & Scoring
print("\n[TEST 7] Testing Search & Scoring...")
try:
    from backend.vectorstore.resume_store import query_resumes
    
    jd_text = """
    Senior Python Developer
    
    Requirements:
    - 5+ years Python experience
    - Django or Flask framework
    - PostgreSQL database
    - AWS cloud experience
    - React frontend (nice to have)
    """
    
    print("   Searching for candidates...")
    results = query_resumes(jd_text, top_k=5)
    
    print(f"✅ Search completed: {len(results)} candidates found")
    
    for i, r in enumerate(results[:3], 1):
        print(f"\n   {i}. {r.get('name', 'Unknown')}")
        print(f"      Title: {r.get('title', 'N/A')}")
        print(f"      Similarity: {r.get('similarity', 0):.4f}")
        skills = r.get('skills', '').split(',')[:5]
        print(f"      Sample skills: {skills}")

except Exception as e:
    print(f"❌ Search test failed: {e}")
    import traceback
    traceback.print_exc()

# Test 8: Full API Test
print("\n[TEST 8] Testing API Endpoints...")
try:
    import requests
    
    # Test if servers are running
    try:
        r = requests.get("http://localhost:8000/", timeout=2)
        print(f"✅ Main API (8000) is running")
    except:
        print("❌ Main API (8000) is NOT running")
        print("   Start with: python start.py")
    
    try:
        r = requests.get("http://localhost:8001/", timeout=2)
        print(f"✅ Agent API (8001) is running")
    except:
        print("❌ Agent API (8001) is NOT running")
        print("   Start with: python start.py agent")

except Exception as e:
    print(f"⚠️  API test skipped: {e}")

# Summary
print("\n" + "="*80)
print("TEST SUMMARY")
print("="*80)
print("""
✅ NO AWS/BEDROCK REQUIRED!

System uses:
- Groq LLM (llama-3.3-70b-versatile) for skill extraction
- HuggingFace (all-MiniLM-L6-v2) for embeddings
- PostgreSQL + pgvector for storage

To run the full system:

1. Start Main API:
   python start.py

2. Start Agent (optional):
   python start.py agent

3. Open Frontend:
   Open: frontend/index.html in browser

4. Test Upload:
   - Click "Upload Resume"
   - Select resume from uploads/
   - Check console for logs

5. Test Search:
   - Paste JD in textarea
   - Click "Add JD + Search Resumes"
   - View results

6. Debug in PyCharm:
   - Set breakpoints in utils/parsing.py
   - Run in Debug mode (Shift+F9)
   - Upload resume from frontend
   - Inspect variables
""")

print("="*80)
print("TESTING COMPLETE")
print("="*80)
