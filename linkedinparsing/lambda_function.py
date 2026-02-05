import os, io, json, boto3, tempfile, traceback, hashlib, re, uuid
from urllib.parse import unquote_plus
from datetime import datetime

import psycopg2
from PyPDF2 import PdfReader

# =========================
# ENV VARS
# =========================
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

DB_NAME = os.getenv("PG_DB", "resumes")
DB_USER = os.getenv("PG_USER", "")
DB_PASS = os.getenv("PG_PASS", "")
DB_HOST = os.getenv("PG_HOST", "")
DB_PORT = os.getenv("PG_PORT", "5432")

BEDROCK_LLM_MODEL = os.getenv("BEDROCK_LLM_MODEL", "us.anthropic.claude-3-5-sonnet-20241022-v2:0")

LOG_CLAUDE_CHARS = int(os.getenv("LOG_CLAUDE_CHARS", "1600"))

# S3 bucket names for mapping
RESUME_BUCKET = os.getenv("RESUME_BUCKET", "")  # e.g., "my-resumes-bucket"
LINKEDIN_BUCKET = os.getenv("LINKEDIN_BUCKET", "")  # e.g., "my-linkedin-profiles-bucket"

s3 = boto3.client("s3", region_name=AWS_REGION)
bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)

# =========================
# HELPERS
# =========================
def pg_conn():
    return psycopg2.connect(dbname=DB_NAME, user=DB_USER, password=DB_PASS, host=DB_HOST, port=DB_PORT)

def sha1_hex(s: str) -> str:
    return hashlib.sha1((s or "").encode("utf-8")).hexdigest()

def extract_pdf_text(file_bytes: bytes) -> str:
    """Extract all text from PDF"""
    pages_text = []
    with io.BytesIO(file_bytes) as pdf_stream:
        reader = PdfReader(pdf_stream)
        for page in reader.pages:
            text = page.extract_text() or ""
            pages_text.append(text)
    return "\n".join(pages_text)

def invoke_claude(prompt: str, max_tokens: int = 3000) -> str:
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
    
    # Strip markdown code fences
    if "```" in text:
        parts = text.split("```")
        text = max(parts, key=len).strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    
    return text.strip()

# =========================
# LINKEDIN VALIDATION
# =========================
def validate_linkedin_pdf(full_text: str) -> dict:
    """
    Use Claude to determine if this is a LinkedIn profile PDF and extract confidence.
    Returns: {"is_linkedin": bool, "confidence": float, "reason": str}
    """
    full_text = (full_text or "")[:15000]  # Limit text for prompt
    
    prompt = f"""
You are a document classifier. Determine if this is a LinkedIn profile PDF export.

Text from PDF:
{full_text}

Return ONLY valid JSON (no markdown):
{{
  "is_linkedin": true/false,
  "confidence": 0.0-1.0,
  "reason": "brief explanation",
  "indicators_found": []
}}

Common LinkedIn PDF indicators:
- "linkedin.com" or "LinkedIn" branding
- "Profile" or "Experience" sections with company names
- "Skills & Endorsements" or "Skills" section
- Date ranges like "Jan 2020 - Present"
- Connection count or follower count
- Profile URL format
- Education section with degree and institution

If you find 3+ strong indicators, mark is_linkedin=true with high confidence.
"""
    
    raw = invoke_claude(prompt, max_tokens=800)
    result = json.loads(raw)
    
    print(f"[VALIDATION] is_linkedin={result.get('is_linkedin')} confidence={result.get('confidence'):.2f} reason={result.get('reason')}")
    print(f"[VALIDATION] indicators={result.get('indicators_found')}")
    
    return result

# =========================
# LINKEDIN SKILL EXTRACTION
# =========================
def extract_linkedin_skills(full_text: str, linkedin_id: str) -> dict:
    """
    Extract skills from LinkedIn profile using Claude.
    Returns comprehensive skill data similar to resume parsing.
    """
    full_text = (full_text or "")[:25000]
    
    prompt = f"""
You are an expert LinkedIn profile parser.

Extract ALL skills mentioned in this LinkedIn profile.
Look in "Skills", "Skills & Endorsements", experience descriptions, and project descriptions.

LinkedIn Profile:
{full_text}

Return ONLY valid JSON (no markdown):
{{
  "linkedin_id": "{linkedin_id}",
  "name": "",
  "headline": "",
  "location": "",
  "profile_url": "",
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
    "tools_platforms": [],
    "soft_skills": []
  }},
  "skills_flat_unique": [],
  "endorsement_counts": {{}},
  "top_skills": [],
  "certifications": [],
  "total_connections": ""
}}

Rules:
- Deduplicate case-insensitive
- Use canonical names (".NET 6", "ASP.NET Core", "PostgreSQL", "Kubernetes")
- If endorsement counts visible, include them in endorsement_counts
- Extract top 3-5 most endorsed skills into top_skills array
- Extract any certifications mentioned
"""
    
    raw = invoke_claude(prompt, max_tokens=3000)
    data = json.loads(raw)
    
    # Ensure skills_flat_unique is populated
    if not data.get("skills_flat_unique"):
        flat = []
        for category, skills_list in (data.get("skills") or {}).items():
            if isinstance(skills_list, list):
                flat.extend(skills_list)
        
        # Deduplicate
        seen, unique = set(), []
        for skill in flat:
            skill = str(skill).strip()
            key = skill.lower()
            if skill and key not in seen:
                seen.add(key)
                unique.append(skill)
        
        data["skills_flat_unique"] = unique
    
    print(f"[SKILLS] extracted from LinkedIn:")
    print(f"  name={data.get('name')} headline={data.get('headline')}")
    print(f"  location={data.get('location')} profile_url={data.get('profile_url')}")
    print(f"  total_skills={len(data.get('skills_flat_unique', []))}")
    print(f"  top_skills={data.get('top_skills')}")
    print(f"  certifications_count={len(data.get('certifications', []))}")
    
    return data

# =========================
# DATABASE OPERATIONS
# =========================
def upsert_linkedin_profile(linkedin_id: str, s3_key: str, file_name: str, s3_uri: str, 
                           validation_result: dict, skills_data: dict):
    """
    Insert or update LinkedIn profile in database.
    """
    skills_flat = skills_data.get("skills_flat_unique", []) or []
    skills_hash = sha1_hex(", ".join(skills_flat))
    
    payload = dict(
        linkedin_id=linkedin_id,
        s3_key=s3_key,
        file_name=file_name,
        s3_uri=s3_uri,
        name=skills_data.get("name", ""),
        headline=skills_data.get("headline", ""),
        location=skills_data.get("location", ""),
        profile_url=skills_data.get("profile_url", ""),
        total_connections=skills_data.get("total_connections", ""),
        validation_confidence=float(validation_result.get("confidence", 0.0)),
        validation_reason=validation_result.get("reason", ""),
        skills_json=json.dumps(skills_data, ensure_ascii=False),
        skills_flat=skills_flat,
        skills_hash=skills_hash,
        endorsement_counts=json.dumps(skills_data.get("endorsement_counts", {})),
        top_skills=skills_data.get("top_skills", []),
        certifications=skills_data.get("certifications", [])
    )
    
    print(f"[PG] upsert linkedin_profiles linkedin_id={linkedin_id} file_name={file_name}")
    
    with pg_conn() as conn, conn.cursor() as cur:
        cur.execute("""
        INSERT INTO resume_data.linkedin_profiles(
          linkedin_id, s3_key, file_name, s3_uri, name, headline, location, profile_url,
          total_connections, validation_confidence, validation_reason,
          skills_json, skills_flat, skills_hash,
          endorsement_counts, top_skills, certifications, updated_at
        ) VALUES (
          %(linkedin_id)s, %(s3_key)s, %(file_name)s, %(s3_uri)s, %(name)s, %(headline)s, 
          %(location)s, %(profile_url)s, %(total_connections)s, %(validation_confidence)s, 
          %(validation_reason)s, %(skills_json)s::jsonb, %(skills_flat)s, %(skills_hash)s,
          %(endorsement_counts)s::jsonb, %(top_skills)s, %(certifications)s, now()
        )
        ON CONFLICT (linkedin_id) DO UPDATE SET
          s3_key=EXCLUDED.s3_key,
          file_name=EXCLUDED.file_name,
          s3_uri=EXCLUDED.s3_uri,
          name=EXCLUDED.name,
          headline=EXCLUDED.headline,
          location=EXCLUDED.location,
          profile_url=EXCLUDED.profile_url,
          total_connections=EXCLUDED.total_connections,
          validation_confidence=EXCLUDED.validation_confidence,
          validation_reason=EXCLUDED.validation_reason,
          skills_json=EXCLUDED.skills_json,
          skills_flat=EXCLUDED.skills_flat,
          skills_hash=EXCLUDED.skills_hash,
          endorsement_counts=EXCLUDED.endorsement_counts,
          top_skills=EXCLUDED.top_skills,
          certifications=EXCLUDED.certifications,
          updated_at=now();
        """, payload)

def find_matching_resume(linkedin_name: str, linkedin_email: str = None) -> str:
    """
    Try to find a matching resume_id based on name or email.
    Returns resume_id if found, None otherwise.
    
    This enables linking LinkedIn profile to resume.
    """
    if not linkedin_name and not linkedin_email:
        return None
    
    with pg_conn() as conn, conn.cursor() as cur:
        # Try exact name match first
        if linkedin_name:
            cur.execute("""
                SELECT resume_id FROM resume_data.resume_profiles 
                WHERE LOWER(name) = LOWER(%s)
                LIMIT 1
            """, (linkedin_name,))
            row = cur.fetchone()
            if row:
                print(f"[MATCH] Found resume by name match: {row[0]}")
                return row[0]
        
        # Try email match
        if linkedin_email:
            cur.execute("""
                SELECT resume_id FROM resume_data.resume_profiles 
                WHERE LOWER(email) = LOWER(%s)
                LIMIT 1
            """, (linkedin_email,))
            row = cur.fetchone()
            if row:
                print(f"[MATCH] Found resume by email match: {row[0]}")
                return row[0]
    
    print("[MATCH] No matching resume found")
    return None

def create_linkedin_resume_mapping(linkedin_id: str, resume_id: str, confidence: float, match_method: str):
    """
    Create a mapping between LinkedIn profile and resume.
    Allows multiple resumes per LinkedIn profile (e.g., different versions).
    """
    mapping_id = str(uuid.uuid4())
    
    with pg_conn() as conn, conn.cursor() as cur:
        cur.execute("""
        INSERT INTO resume_data.linkedin_resume_mapping(
          id, linkedin_id, resume_id, match_confidence, match_method, created_at
        ) VALUES (
          %s, %s, %s, %s, %s, now()
        )
        ON CONFLICT (linkedin_id, resume_id) DO UPDATE SET
          match_confidence=EXCLUDED.match_confidence,
          match_method=EXCLUDED.match_method,
          created_at=now();
        """, (mapping_id, linkedin_id, resume_id, confidence, match_method))
    
    print(f"[MAPPING] Created linkedin_id={linkedin_id} <-> resume_id={resume_id} (method={match_method})")

# =========================
# MAIN HANDLER
# =========================
def lambda_handler(event, context):
    print(f"[INIT] region={AWS_REGION} resume_bucket={RESUME_BUCKET} linkedin_bucket={LINKEDIN_BUCKET}")
    
    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        key = unquote_plus(record["s3"]["object"]["key"])
        s3_key = key
        file_name = key.split("/")[-1]
        s3_uri = f"s3://{bucket}/{key}"
        
        # Generate linkedin_id from s3_key (similar to resume_id generation)
        linkedin_id = sha1_hex(s3_key)
        
        print(f"\n[INGEST] file=s3://{bucket}/{key}")
        print(f"[INGEST] linkedin_id(sha1)={linkedin_id}")
        
        # Download file
        obj = s3.get_object(Bucket=bucket, Key=key)
        file_bytes = obj["Body"].read()
        
        # Only support PDF for LinkedIn profiles
        if not key.lower().endswith(".pdf"):
            print(f"[INGEST] ❌ only PDF supported for LinkedIn profiles, got: {key}")
            continue
        
        # Extract text
        full_text = extract_pdf_text(file_bytes)
        print(f"[TEXT] chars={len(full_text)}")
        print(f"[TEXT] preview:\n{full_text[:800]}")
        
        if not full_text.strip():
            print("[INGEST] ❌ empty text, skip")
            continue
        
        # STEP 1: Validate it's a LinkedIn PDF
        validation = validate_linkedin_pdf(full_text)
        
        if not validation.get("is_linkedin"):
            print(f"[INGEST] ❌ NOT a LinkedIn profile (confidence={validation.get('confidence'):.2f})")
            print(f"[INGEST] Reason: {validation.get('reason')}")
            # Still store with low confidence for manual review
            validation["confidence"] = 0.0
        
        # STEP 2: Extract skills even if validation uncertain (for manual review)
        skills_data = extract_linkedin_skills(full_text, linkedin_id)
        
        # STEP 3: Store LinkedIn profile
        upsert_linkedin_profile(linkedin_id, s3_key, file_name, s3_uri, validation, skills_data)
        
        # STEP 4: Try to find matching resume
        linkedin_name = skills_data.get("name", "")
        linkedin_email = None  # LinkedIn PDFs usually don't show email
        
        resume_id = find_matching_resume(linkedin_name, linkedin_email)
        
        if resume_id:
            # Create mapping with high confidence if validation passed
            mapping_confidence = validation.get("confidence", 0.5)
            create_linkedin_resume_mapping(
                linkedin_id, 
                resume_id, 
                mapping_confidence, 
                "name_match"
            )
        else:
            print("[MAPPING] ⚠️ No matching resume found. Manual mapping may be needed.")
            print(f"[MAPPING] LinkedIn name: {linkedin_name}")
        
        print(f"[INGEST] ✅ done linkedin_id={linkedin_id}")
    
    return {"statusCode": 200, "body": "ok"}
