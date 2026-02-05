"""
Updated Resume Parsing Lambda - WITH Skill Experience Extraction
=================================================================

Based on: lambda_function_pv1.py (keeps all existing functionality)
Adds: Skill experience extraction and storage

Flow:
1. Extract text (SAME)
2. Extract skills (SAME)
3. Create chunks and embeddings (SAME)
4. NEW: Extract skill experience breakdown
5. Store everything (ENHANCED)
"""

import os, io, json, boto3, tempfile, traceback, hashlib, re, uuid
from urllib.parse import unquote_plus
from datetime import datetime

import psycopg2
import docx2txt
from PyPDF2 import PdfReader

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

DB_NAME = os.getenv("PG_DB", "resumes")
DB_USER = os.getenv("PG_USER", "")
DB_PASS = os.getenv("PG_PASS", "")
DB_HOST = os.getenv("PG_HOST", "")
DB_PORT = os.getenv("PG_PORT", "5432")

VECTOR_BUCKET = os.getenv("VECTOR_BUCKET")
VECTOR_INDEX  = os.getenv("VECTOR_INDEX")
BATCH_SIZE    = int(os.getenv("BATCH_SIZE", "10"))

BEDROCK_EMBED_MODEL = os.getenv("BEDROCK_EMBED_MODEL", "amazon.titan-embed-text-v2:0")
BEDROCK_LLM_MODEL   = os.getenv("BEDROCK_LLM_MODEL", "us.anthropic.claude-3-5-sonnet-20241022-v2:0")

LOG_CLAUDE_CHARS = int(os.getenv("LOG_CLAUDE_CHARS", "1600"))

s3 = boto3.client("s3", region_name=AWS_REGION)
bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)
s3vector = boto3.client("s3vectors", region_name=AWS_REGION)

def pg_conn():
    return psycopg2.connect(dbname=DB_NAME, user=DB_USER, password=DB_PASS, host=DB_HOST, port=DB_PORT)

def sha1_hex(s: str) -> str:
    return hashlib.sha1((s or "").encode("utf-8")).hexdigest()

def canonical_resume_id(s3_key: str) -> str:
    return sha1_hex(s3_key)

def extract_docx_text(file_bytes: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        tmp.write(file_bytes); tmp.flush()
        path = tmp.name
    try:
        return docx2txt.process(path) or ""
    finally:
        try: os.unlink(path)
        except: pass

def extract_pdf_pages(file_bytes: bytes):
    pages = []
    with io.BytesIO(file_bytes) as pdf_stream:
        reader = PdfReader(pdf_stream)
        for i, p in enumerate(reader.pages):
            pages.append({"page_number": i+1, "text": p.extract_text() or ""})
    return pages

def chunk_text(text, chunk_words=250, overlap=50):
    words = (text or "").split()
    chunks, start = [], 0
    while start < len(words):
        end = min(len(words), start + chunk_words)
        chunk = " ".join(words[start:end]).strip()
        if chunk:
            chunks.append(chunk)
        if end == len(words):
            break
        start = max(0, end - overlap)
    return chunks

def clean_json_response(text: str) -> str:
    """Remove JSON wrappers."""
    text = text.strip()
    
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()
    
    if not text.startswith("{") and not text.startswith("["):
        json_start = text.find("{")
        if json_start != -1:
            text = text[json_start:]
    
    return text

def invoke_claude(prompt: str, max_tokens: int = 2500) -> str:
    print(f"[CLAUDE] model={BEDROCK_LLM_MODEL} max_tokens={max_tokens}")
    print(f"[CLAUDE] prompt preview:\n{prompt[:600]}...")
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0
    }
    resp = bedrock.invoke_model(modelId=BEDROCK_LLM_MODEL, body=json.dumps(body))
    result = json.loads(resp["body"].read())
    text = result["content"][0]["text"].strip()
    print(f"[CLAUDE] raw chars={len(text)} preview:\n{text[:LOG_CLAUDE_CHARS]}...")
    
    text = clean_json_response(text)
    return text

def get_embedding(text: str):
    body = {"inputText": (text or "")[:8000]}
    resp = bedrock.invoke_model(
        modelId=BEDROCK_EMBED_MODEL,
        body=json.dumps(body),
        accept="application/json",
        contentType="application/json"
    )
    emb = json.loads(resp["body"].read())["embedding"]
    print(f"[EMBED] dims={len(emb)} text_preview={text[:90]}...")
    return emb

def find_linkedin(full_text: str) -> str:
    if not full_text:
        return ""
    m = re.search(r"(https?://(www\.)?linkedin\.com/[^\s)>,]+)", full_text, flags=re.I)
    if m: return m.group(1).strip()
    m2 = re.search(r"((www\.)?linkedin\.com/[^\s)>,]+)", full_text, flags=re.I)
    if m2:
        v = m2.group(1).strip()
        return v if v.lower().startswith("http") else ("https://" + v)
    return ""

def extract_full_skills(full_text: str, resume_id: str) -> dict:
    """UNCHANGED - Same as lambda_function_pv1.py"""
    full_text = (full_text or "")[:100000]
    prompt = f"""
You are an expert ATS resume parser.

Extract ALL skills mentioned ANYWHERE (skills section + bullets + responsibilities + projects).
Also extract name/email/phone/location/title/years_exp and LinkedIn if present.

Return ONLY valid JSON (no markdown).

Resume:
{full_text}

Return JSON:
{{
  "resume_id": "{resume_id}",
  "name": "",
  "email": "",
  "phone": "",
  "location": "",
  "linkedin_url": "",
  "title": "",
  "years_exp": "",
  "summary_one_line": "",
  "skills": {{
    "programming_languages": [],
    "dotnet_microsoft": [],
    "frontend_web": [],
    "cloud_aws": [],
    "cloud_azure": [],
    "cloud_gcp": [],
    "devops_cicd_iac": [],
    "containers_kubernetes": [],
    "databases_data": [],
    "messaging_streaming": [],
    "security_identity": [],
    "testing_quality": [],
    "observability_monitoring": [],
    "architecture_patterns": [],
    "ai_ml_llm_vector": [],
    "tools_platforms": []
  }},
  "skills_flat_unique": []
}}
Rules:
- Deduplicate case-insensitive.
- Use canonical names (".NET 6", "ASP.NET Core", "PostgreSQL").
"""
    raw = invoke_claude(prompt)
    data = json.loads(raw)

    if not data.get("linkedin_url"):
        data["linkedin_url"] = find_linkedin(full_text)

    if not data.get("skills_flat_unique"):
        flat = []
        for _, arr in (data.get("skills") or {}).items():
            if isinstance(arr, list): flat.extend(arr)
        seen, uniq = set(), []
        for x in flat:
            x = str(x).strip()
            k = x.lower()
            if x and k not in seen:
                seen.add(k); uniq.append(x)
        data["skills_flat_unique"] = uniq

    print("[SKILLS] extracted summary:")
    print(f"  name={data.get('name')} email={data.get('email')} phone={data.get('phone')}")
    print(f"  location={data.get('location')} linkedin={data.get('linkedin_url')}")
    print(f"  title={data.get('title')} years_exp={data.get('years_exp')}")
    print(f"  skills_count={len(data.get('skills_flat_unique', []))}")
    return data

# =========================
# NEW: Skill Experience Extraction
# =========================

def extract_skill_experience_breakdown(full_text: str, skills_list: list) -> dict:
    """Extract experience from FULL resume text."""

    if not skills_list:
        print("[SKILL_EXP] No skills to extract experience for")
        return {}

    full_text_for_analysis = full_text[:100000]

    print(f"[SKILL_EXP] Full text: {len(full_text)} chars")
    print(f"[SKILL_EXP] Using: {len(full_text_for_analysis)} chars")

    # Process in batches
    all_results = {}
    batch_size = 10

    for i in range(0, len(skills_list), batch_size):
        batch_skills = skills_list[i:i + batch_size]
        skills_str = ", ".join(batch_skills)

        print(f"[SKILL_EXP] Batch {i // batch_size + 1}: Processing {len(batch_skills)} skills")

        prompt = f"""Extract work experience for these skills from the resume.

Skills: {skills_str}

Resume:
{full_text_for_analysis}

Return ONE JSON object:
{{
  "skill1": {{"jobs_using_skill": [{{"company": "X", "start_date": "YYYY-MM", "end_date": "YYYY-MM", "duration_months": N, "evidence": "..."}}]}},
  "skill2": {{"jobs_using_skill": [...]}}
}}

Variants (treat as same):
- AWS EC2 = Amazon EC2 = EC2
- .NET = dotnet = ASP.NET = C# = .NET 6

Rules:
- Return ONE object with ALL skills
- Only include skills USED in work (not just listed)
- Scan ENTIRE work history
- Calculate duration_months accurately
- If skill not used, return empty array: {{"jobs_using_skill": []}}"""

        try:
            raw = invoke_claude(prompt, max_tokens=4000)

            # Clean
            raw = raw.strip()
            start = raw.find('{')
            end = raw.rfind('}')

            if start == -1 or end == -1:
                print(f"[SKILL_EXP] No JSON in response")
                continue

            raw = raw[start:end + 1]

            # Check for multiple objects
            if '}{' in raw:
                print(f"[SKILL_EXP] ⚠️ Multiple JSON objects, taking first")
                raw = raw[:raw.find('}{') + 1]

            batch_data = json.loads(raw)

            # MERGE with existing results (don't overwrite)
            for skill, skill_data in batch_data.items():
                if skill in all_results:
                    # Skill already exists - merge jobs
                    existing_jobs = all_results[skill].get("jobs_using_skill", [])
                    new_jobs = skill_data.get("jobs_using_skill", [])

                    # Combine and deduplicate by company
                    all_jobs = existing_jobs + new_jobs
                    seen_companies = set()
                    merged_jobs = []

                    for job in all_jobs:
                        company = job.get("company", "")
                        if company and company not in seen_companies:
                            seen_companies.add(company)
                            merged_jobs.append(job)

                    all_results[skill]["jobs_using_skill"] = merged_jobs
                    print(f"[SKILL_EXP]   Merged {skill}: {len(merged_jobs)} jobs")
                else:
                    # New skill - add it
                    all_results[skill] = skill_data
                    print(f"[SKILL_EXP]   New {skill}: {len(skill_data.get('jobs_using_skill', []))} jobs")

            print(f"[SKILL_EXP] ✅ Batch {i // batch_size + 1}: Processed {len(batch_data)} skills")

        except json.JSONDecodeError as e:
            print(f"[SKILL_EXP] ❌ JSON error: {e}")
            print(f"[SKILL_EXP] Raw (first 300): {raw[:300]}")
            continue

        except Exception as e:
            print(f"[SKILL_EXP] ❌ Error: {e}")
            traceback.print_exc()
            continue

    # Calculate total_years AFTER all batches
    for skill, skill_data in all_results.items():
        if isinstance(skill_data, dict) and "jobs_using_skill" in skill_data:
            jobs = skill_data["jobs_using_skill"]

            if not jobs:
                skill_data["total_years"] = 0.0
                continue

            # FIX: Handle None values in duration_months
            total_months = 0
            for j in jobs:
                months = j.get("duration_months")
                if months is not None:  # Check for None
                    total_months += int(months)  # Convert to int in case it's float

            skill_data["total_years"] = round(total_months / 12.0, 1)

            print(f"[SKILL_EXP] {skill}: {skill_data['total_years']}y across {len(jobs)} jobs")
            for job in jobs:
                months = job.get("duration_months", 0)
                print(f"[SKILL_EXP]   - {job.get('company')}: {months if months else 0}m")

    print(f"[SKILL_EXP] ✅ Total: {len(all_results)} skills extracted")
    return all_results

# =========================
# Database Operations
# =========================

def upsert_profile(resume_id, s3_key, file_name, s3_uri, skills_data, skill_experience: dict = None):
    """ENHANCED: Now stores skill_experience_json"""
    
    skills_flat = skills_data.get("skills_flat_unique", []) or []
    skills_hash = sha1_hex(", ".join(skills_flat))

    years = 0
    try:
        m = re.search(r"\d+", str(skills_data.get("years_exp","0")))
        years = int(m.group()) if m else 0
    except:
        years = 0

    payload = dict(
        resume_id=resume_id, s3_key=s3_key, file_name=file_name, s3_uri=s3_uri,
        name=skills_data.get("name",""),
        email=skills_data.get("email",""),
        phone=skills_data.get("phone",""),
        location=skills_data.get("location",""),
        linkedin_url=skills_data.get("linkedin_url",""),
        title=skills_data.get("title",""),
        years_exp=years,
        summary_one_line=skills_data.get("summary_one_line",""),
        skills_json=json.dumps(skills_data, ensure_ascii=False),
        skills_flat=skills_flat,
        skills_hash=skills_hash,
        skill_experience_json=json.dumps(skill_experience or {}, ensure_ascii=False)  # NEW
    )

    print(f"[PG] upsert resume_profiles resume_id={resume_id} file_name={file_name}")
    print(f"[PG] skill_experience_json: {len(skill_experience or {})} skills with work evidence")
    
    with pg_conn() as conn, conn.cursor() as cur:
        # Check if column exists
        cur.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_schema='resume_data' 
            AND table_name='resume_profiles' 
            AND column_name='skill_experience_json'
        """)
        
        has_skill_exp_column = cur.fetchone() is not None
        
        if has_skill_exp_column:
            # Use new column
            cur.execute("""
            INSERT INTO resume_data.resume_profiles(
              resume_id,s3_key,file_name,s3_uri,name,email,phone,location,linkedin_url,title,years_exp,
              summary_one_line,skills_json,skills_flat,skills_hash,skill_experience_json,updated_at
            ) VALUES (
              %(resume_id)s,%(s3_key)s,%(file_name)s,%(s3_uri)s,%(name)s,%(email)s,%(phone)s,%(location)s,%(linkedin_url)s,%(title)s,%(years_exp)s,
              %(summary_one_line)s,%(skills_json)s::jsonb,%(skills_flat)s,%(skills_hash)s,%(skill_experience_json)s::jsonb,now()
            )
            ON CONFLICT (resume_id) DO UPDATE SET
              s3_key=EXCLUDED.s3_key,
              file_name=EXCLUDED.file_name,
              s3_uri=EXCLUDED.s3_uri,
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
            """, payload)
            print("[PG] ✅ Stored with skill_experience_json")
        else:
            # Old schema without skill_experience_json
            print("[PG] ⚠️ skill_experience_json column not found, skipping")
            cur.execute("""
            INSERT INTO resume_data.resume_profiles(
              resume_id,s3_key,file_name,s3_uri,name,email,phone,location,linkedin_url,title,years_exp,
              summary_one_line,skills_json,skills_flat,skills_hash,updated_at
            ) VALUES (
              %(resume_id)s,%(s3_key)s,%(file_name)s,%(s3_uri)s,%(name)s,%(email)s,%(phone)s,%(location)s,%(linkedin_url)s,%(title)s,%(years_exp)s,
              %(summary_one_line)s,%(skills_json)s::jsonb,%(skills_flat)s,%(skills_hash)s,now()
            )
            ON CONFLICT (resume_id) DO UPDATE SET
              s3_key=EXCLUDED.s3_key,
              file_name=EXCLUDED.file_name,
              s3_uri=EXCLUDED.s3_uri,
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
              updated_at=now();
            """, payload)

def insert_chunk(resume_id, vector_key, page, chunk_index, chunk_text) -> str:
    """UNCHANGED - Same as lambda_function_pv1.py"""
    chunk_id = str(uuid.uuid4())
    with pg_conn() as conn, conn.cursor() as cur:
        cur.execute("""
        INSERT INTO resume_data.resume_chunks(id,resume_id,vector_key,page,chunk_index,chunk_text)
        VALUES (%s,%s,%s,%s,%s,%s)
        ON CONFLICT (vector_key) DO UPDATE SET chunk_text=EXCLUDED.chunk_text
        """, (chunk_id, resume_id, vector_key, page, chunk_index, chunk_text))
    return chunk_id

def put_batch(vectors):
    """UNCHANGED - Same as lambda_function_pv1.py"""
    if not vectors: return
    try:
        resp = s3vector.put_vectors(vectorBucketName=VECTOR_BUCKET, indexName=VECTOR_INDEX, vectors=vectors)
        print(f"[S3V][PUT] ✅ batch={len(vectors)} resp_keys={list(resp.keys())}")
    except Exception as e:
        print(f"[S3V][PUT] ❌ batch={len(vectors)} error={e}")
        traceback.print_exc()
        raise

def ingest_chunks(resume_id, pages, s3_key, s3_uri, file_name, candidate_name):
    """UNCHANGED - Same as lambda_function_pv1.py"""
    print(f"[CHUNKS] resume_id={resume_id} pages={len(pages)}")
    batch = []
    
    for page in pages:
        pno = int(page["page_number"])
        chunks = chunk_text(page.get("text",""))
        print(f"[CHUNKS] page={pno} chunks={len(chunks)}")
        
        for idx, chunk in enumerate(chunks):
            vector_key = f"{resume_id}_p{pno}_c{idx}"
            chunk_id = insert_chunk(resume_id, vector_key, pno, idx, chunk)
            emb = get_embedding(chunk)

            md = {
                "type": "content",
                "resume_id": resume_id,
                "chunk_id": chunk_id,
                "page": str(pno),
                "chunk_index": str(idx),
                "file_name": file_name[:180],
                "s3_key": s3_key[:500],
                "s3_uri": s3_uri[:500],
                "candidate_name": (candidate_name or "Unknown")[:120],
                "chunk_preview": chunk[:250],
            }

            batch.append({"key": vector_key, "data": {"float32": emb}, "metadata": md})

            if len(batch) >= BATCH_SIZE:
                put_batch(batch); batch = []
    
    if batch:
        put_batch(batch)

# =========================
# Lambda Handler
# =========================

def lambda_handler(event, context):
    print(f"[INIT] region={AWS_REGION} bucket={VECTOR_BUCKET} index={VECTOR_INDEX}")
    if not VECTOR_BUCKET or not VECTOR_INDEX:
        raise ValueError(f"Missing VECTOR_BUCKET/VECTOR_INDEX bucket={VECTOR_BUCKET} index={VECTOR_INDEX}")

    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        key = unquote_plus(record["s3"]["object"]["key"])
        s3_key = key.removeprefix("resume/")
        file_name = key.split("/")[-1]
        s3_uri = f"s3://{bucket}/{key}"

        resume_id = canonical_resume_id(s3_key)
        print(f"\n[INGEST] s3key={s3_key}")
        print(f"\n[INGEST] file=s3://{bucket}/{key}")
        print(f"[INGEST] resume_id(sha1)={resume_id}")

        obj = s3.get_object(Bucket=bucket, Key=key)
        file_bytes = obj["Body"].read()

        if key.lower().endswith(".pdf"):
            pages = extract_pdf_pages(file_bytes)
            full_text = "\n".join([p["text"] for p in pages])
        elif key.lower().endswith(".docx"):
            full_text = extract_docx_text(file_bytes)
            pages = [{"page_number": 1, "text": full_text}]
        else:
            print("[INGEST] unsupported:", key)
            continue

        print(f"[TEXT] chars={len(full_text)}")

        if not full_text.strip():
            print("[INGEST] empty text, skip"); continue

        # STEP 1: Extract skills (SAME AS BEFORE)
        skills_data = extract_full_skills(full_text, resume_id)
        
        # STEP 2: Extract skill experience breakdown (NEW!)
        skills_list = skills_data.get("skills_flat_unique", [])
        skill_experience = extract_skill_experience_breakdown(full_text, skills_list)
        
        # STEP 3: Store profile with skill experience (ENHANCED)
        upsert_profile(resume_id, s3_key, file_name, s3_uri, skills_data, skill_experience)
        
        # STEP 4: Create chunks and embeddings (SAME AS BEFORE)
        ingest_chunks(resume_id, pages, s3_key, s3_uri, file_name, skills_data.get("name","Unknown"))

        print(f"[INGEST] ✅ done resume_id={resume_id}")

    return {"statusCode": 200, "body": "ok"}
