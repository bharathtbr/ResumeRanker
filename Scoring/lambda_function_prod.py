"""
Resume Scoring Lambda Function
Reads resumes from S3, retrieves JD from PostgreSQL, and scores using AWS Bedrock
Enhanced to extract skill-specific experience from resume with comprehensive job extraction
"""

import os, io, json, boto3, tempfile, traceback, hashlib, re, uuid
from urllib.parse import unquote_plus
from datetime import datetime

import psycopg2
from psycopg2.extras import RealDictCursor
import docx2txt
from PyPDF2 import PdfReader

# Initialize AWS clients
s3_client = boto3.client('s3')
bedrock_runtime = boto3.client('bedrock-runtime', region_name=os.environ.get('AWS_REGION', 'us-east-1'))

# Database configuration
DB_NAME = os.getenv("PG_DB", "resumes")
DB_USER = os.getenv("PG_USER", "")
DB_PASS = os.getenv("PG_PASS", "")
DB_HOST = os.getenv("PG_HOST", "")
DB_PORT = os.getenv("PG_PORT", "5432")

BEDROCK_MODEL_ID = os.environ.get('BEDROCK_MODEL_ID', 'us.anthropic.claude-3-5-sonnet-20241022-v2:0')

# Debug settings
DEBUG = os.environ.get('DEBUG', 'true').lower() == 'true'
LOG_PROMPT_CHARS = int(os.environ.get('LOG_PROMPT_CHARS', '500'))
LOG_RESPONSE_CHARS = int(os.environ.get('LOG_RESPONSE_CHARS', '800'))


def log(msg: str):
    """Print log message"""
    print(msg)


def debug_log(msg: str):
    """Print debug message if DEBUG enabled"""
    if DEBUG:
        print(f"[DEBUG] {msg}")


def preview(text: str, max_chars: int) -> str:
    """Preview text with truncation"""
    if not text:
        return ""
    text = str(text)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"... (truncated, total {len(text)} chars)"


def extract_json_from_text(text: str) -> str:
    """Extract JSON from text that may have markdown or extra content"""
    # Remove markdown code blocks
    if "```json" in text.lower():
        # Extract content between ```json and ```
        match = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
    elif "```" in text:
        # Extract content between ``` and ```
        match = re.search(r'```\s*(.*?)\s*```', text, re.DOTALL)
        if match:
            return match.group(1).strip()

    # Try to find JSON object boundaries
    # Look for the first { and last }
    first_brace = text.find('{')
    last_brace = text.rfind('}')

    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        json_text = text[first_brace:last_brace + 1]
        return json_text

    return text


def pg_conn():
    """Create PostgreSQL connection"""
    return psycopg2.connect(dbname=DB_NAME, user=DB_USER, password=DB_PASS, host=DB_HOST, port=DB_PORT)


class ResumeReader:
    """Reads resumes from S3"""

    @staticmethod
    def read_from_s3(bucket: str, key: str) -> str:
        log(f"[S3] Reading file from s3://{bucket}/{key}")
        try:
            debug_log(f"Calling s3_client.get_object(Bucket={bucket}, Key={key})")
            response = s3_client.get_object(Bucket=bucket, Key=key)
            file_content = response['Body'].read()
            debug_log(f"Downloaded {len(file_content)} bytes")

            if key.lower().endswith('.pdf'):
                log("[S3] Detected PDF format")
                return ResumeReader._extract_from_pdf(file_content)
            elif key.lower().endswith('.docx'):
                log("[S3] Detected DOCX format")
                return ResumeReader._extract_from_docx(file_content)
            elif key.lower().endswith('.txt'):
                log("[S3] Detected TXT format")
                return file_content.decode('utf-8')
            else:
                raise ValueError(f"Unsupported file format: {key}")
        except Exception as e:
            log(f"[S3] ❌ Error reading from S3: {str(e)}")
            raise Exception(f"Error reading from S3: {str(e)}")

    @staticmethod
    def _extract_from_pdf(file_content: bytes) -> str:
        """Extract text from PDF using PyPDF2"""
        debug_log("Extracting text from PDF...")
        pdf_file = io.BytesIO(file_content)
        pdf_reader = PdfReader(pdf_file)

        total_pages = len(pdf_reader.pages)
        debug_log(f"PDF has {total_pages} pages")

        text = ""
        for i, page in enumerate(pdf_reader.pages):
            page_text = page.extract_text()
            text += page_text + "\n"
            debug_log(f"Page {i + 1}/{total_pages}: extracted {len(page_text)} chars")

        result = text.strip()
        log(f"[S3] ✅ Extracted {len(result)} chars from PDF ({total_pages} pages)")
        return result

    @staticmethod
    def _extract_from_docx(file_content: bytes) -> str:
        """Extract text from DOCX using docx2txt"""
        debug_log("Extracting text from DOCX...")
        with tempfile.NamedTemporaryFile(delete=False, suffix='.docx') as tmp_file:
            tmp_file.write(file_content)
            tmp_file.flush()
            tmp_path = tmp_file.name
            debug_log(f"Created temp file: {tmp_path}")

            text = docx2txt.process(tmp_path)
            os.unlink(tmp_path)
            debug_log(f"Deleted temp file: {tmp_path}")

        result = text.strip()
        log(f"[S3] ✅ Extracted {len(result)} chars from DOCX")
        return result


def invoke_claude(prompt: str, max_tokens: int = 2000) -> str:
    """Invoke Claude via Bedrock"""
    log(f"[CLAUDE] Invoking model={BEDROCK_MODEL_ID} max_tokens={max_tokens}")
    debug_log(f"Prompt preview:\n{preview(prompt, LOG_PROMPT_CHARS)}")

    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0
    }

    debug_log(f"Request body size: {len(json.dumps(body))} bytes")

    try:
        resp = bedrock_runtime.invoke_model(modelId=BEDROCK_MODEL_ID, body=json.dumps(body))
        result = json.loads(resp["body"].read())

        debug_log(f"Response keys: {list(result.keys())}")

        text = (result.get("content", [{}])[0].get("text") or "").strip()

        log(f"[CLAUDE] ✅ Received response: {len(text)} chars")
        debug_log(f"Response preview:\n{preview(text, LOG_RESPONSE_CHARS)}")

        return text.strip()

    except Exception as e:
        log(f"[CLAUDE] ❌ Error invoking Claude: {str(e)}")
        debug_log(traceback.format_exc())
        raise


def get_job_description(jd_id: int):
    """Get job description from database"""
    log(f"[DB] Fetching JD id={jd_id}")

    try:
        with pg_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            query = "SELECT * FROM resume_data.job_descriptions WHERE id=%s AND is_active=TRUE"
            debug_log(f"Executing query: {query}")
            debug_log(f"Parameters: id={jd_id}")

            cur.execute(query, (jd_id,))
            row = cur.fetchone()

            if not row:
                log("[DB] ❌ JD not found")
                return None

            row = dict(row)
            log(f"[DB] ✅ Found JD: {row.get('title')}")
            debug_log(f"JD keys: {list(row.keys())}")
            debug_log(f"Description length: {len(row.get('description', ''))} chars")

            return row

    except Exception as e:
        log(f"[DB] ❌ Error fetching JD: {str(e)}")
        debug_log(traceback.format_exc())
        raise


def extract_jd_requirements(jd_text: str) -> dict:
    """Extract JD requirements using Claude"""
    jd_text = (jd_text or "")[:100000]
    log(f"[JD_EXTRACT] Extracting requirements from {len(jd_text)} chars")

    prompt = f"""
Extract requirements from this Job Description.
Return ONLY valid JSON, no markdown, no extra text.

JD:
{jd_text}

Return this exact JSON structure:
{{
  "job_title": "",
  "core_skills": [
    {{"name":"","importance":"critical|required|preferred","min_years":0,"variants":[]}}
  ],
  "secondary_skills": [
    {{"name":"","importance":"required","min_years":0,"variants":[]}}
  ],
  "nice_to_have_skills": [
    {{"name":"","importance":"preferred","variants":[]}}
  ],
  "keywords": [],
  "experience_requirements": {{"total_years":0}}
}}

Rules:
- For ".NET / dotnet": variants MUST include ["dotnet",".net","ASP.NET","ASP.NET Core",".NET 6",".NET 7",".NET 8","C#","Web API","Entity Framework","EF Core"].
- For "AWS": include ["AWS","Amazon Web Services","Amazon EC2","EC2","AWS Lambda","Lambda","Amazon EKS","EKS","S3","RDS"] when mentioned.
- For "PostgreSQL": include ["postgres","postgresql","RDS Postgres","Aurora PostgreSQL"].
- For Kubernetes: include ["kubernetes","k8s","EKS","AKS"].
- For CI/CD: include ["CI/CD","pipelines","GitHub Actions","Jenkins","Azure DevOps"] when mentioned.

Return ONLY the JSON, nothing else.
"""

    raw = invoke_claude(prompt, max_tokens=5000)

    try:
        # Extract JSON from response
        json_text = extract_json_from_text(raw)
        debug_log(f"Extracted JSON text ({len(json_text)} chars)")

        jd = json.loads(json_text)
        log(f"[JD_EXTRACT] ✅ Extracted job_title={jd.get('job_title')}")
        log(f"[JD_EXTRACT] ✅ Core skills: {len(jd.get('core_skills', []))}")
        log(f"[JD_EXTRACT] ✅ Secondary skills: {len(jd.get('secondary_skills', []))}")
        log(f"[JD_EXTRACT] ✅ Nice-to-have skills: {len(jd.get('nice_to_have_skills', []))}")

        core_skills_list = [s.get('name') for s in jd.get('core_skills', [])]
        debug_log(f"Core skills: {core_skills_list}")

        return jd

    except json.JSONDecodeError as e:
        log(f"[JD_EXTRACT] ❌ Failed to parse JSON: {str(e)}")
        log(f"[JD_EXTRACT] Raw response length: {len(raw)}")
        debug_log(f"Raw response:\n{raw}")
        raise


def analyze_resume_with_claude(resume_text: str) -> dict:
    """Extract COMPLETE structured info from resume with skill-specific experience"""
    log(f"[RESUME_ANALYZE] Analyzing resume ({len(resume_text)} chars)")

    prompt = f"""
Extract and structure the COMPLETE work experience from the provided resume text into this exact JSON format.

Resume:
{resume_text[:100000]}

Rules you MUST follow strictly:
1. Scan the ENTIRE "WORK HISTORY", "Experience", "Professional Experience" or similar section from beginning to end — do NOT stop early.
2. Identify EVERY job entry, even if the text is poorly formatted, concatenated, missing line breaks, or has glued elements (e.g., "~1 year 5 months6Company..." must be split correctly).
3. Detect job boundaries using these reliable patterns (in order of priority):
   - Company name (often includes "Pvt Ltd", "Inc.", "LLC", client names in parentheses)
   - Location (city, state/country e.g. Hyderabad, India | Pittsburgh, PA, USA)
   - Job title (e.g. Lead Developer, Software Engineer, Sr. Developer, Architect)
   - Date range (formats like: MMM YYYY – MMM YYYY, Month Year to Month Year, Nov 2025 – Present)
   - Duration indicators (e.g. ~X years Y months, X years)
4. List ALL detected jobs in **reverse chronological order** (most recent first).
5. Include EVERY job you find — do NOT skip, summarize, or group older/early-career jobs unless the resume itself does so (e.g. has an "Early Career" section).
6. If a job has very little detail, still include it with whatever information is available.
7. Calculate approximate "duration_years" as a float (examples: 1 year 5 months → 1.4, 3 years 1 month → 3.1, 6 months → 0.5, ongoing → use current date to estimate).
8. For "responsibilities": provide a concise 1-3 sentence summary of key duties, achievements, and technologies mentioned for that role.
9. For "technologies_used": list only the major technologies/frameworks/tools explicitly mentioned or strongly implied for that specific job.
10. Output ONLY valid JSON — no explanations, no extra text, no markdown.

Return this exact structure:
{{
  "skills": ["skill1", "skill2"],
  "total_experience_years": 0.0,
  "education": ["degree and institution with years"],
  "work_experience": [
    {{
      "company": "Full company name (include clients in parentheses if present)",
      "title": "Exact or closest title",
      "duration_years": 0.0,
      "start_date": "Month Year",
      "end_date": "Month Year or Present",
      "technologies_used": ["tech1", "tech2"],
      "responsibilities": "Short summary of key responsibilities and achievements"
    }}
  ],
  "skill_experience": {{
    "MajorSkill1": {{
      "total_years": 0.0,
      "projects": [
        {{
          "company": "",
          "project_name": "",
          "duration_years": 0.0,
          "description": ""
        }}
      ]
    }}
  }},
  "certifications": ["cert1 or empty array if none"],
  "projects": ["Notable project 1", "Notable project 2"]
}}

CRITICAL: 
- Extract ALL jobs from the resume (could be 2, 5, 10, or more)
- Sum all individual job durations to get total_experience_years
- For skill_experience: calculate how many years each MAJOR skill was used across ALL jobs
- Include 3-6 major skills in skill_experience with their total years and project examples

Return ONLY the JSON, nothing else.
"""

    raw = invoke_claude(prompt, max_tokens=10000)

    try:
        # Extract JSON from response
        json_text = extract_json_from_text(raw)
        debug_log(f"Extracted JSON text ({len(json_text)} chars)")

        resume_info = json.loads(json_text)
        log(f"[RESUME_ANALYZE] ✅ Found {len(resume_info.get('skills', []))} skills")
        log(f"[RESUME_ANALYZE] ✅ Total experience: {resume_info.get('total_experience_years', 0)} years")
        log(f"[RESUME_ANALYZE] ✅ Skill-specific experience: {len(resume_info.get('skill_experience', {}))} skills tracked")
        log(f"[RESUME_ANALYZE] ✅ Education: {len(resume_info.get('education', []))} entries")
        log(f"[RESUME_ANALYZE] ✅ Work experience: {len(resume_info.get('work_experience', []))} jobs")
        log(f"[RESUME_ANALYZE] ✅ Certifications: {len(resume_info.get('certifications', []))}")
        log(f"[RESUME_ANALYZE] ✅ Projects: {len(resume_info.get('projects', []))}")

        # Log all job companies found
        jobs = resume_info.get('work_experience', [])
        if isinstance(jobs, list) and len(jobs) > 0:
            debug_log(f"Jobs found:")
            for i, job in enumerate(jobs[:10], 1):  # Log first 10
                if isinstance(job, dict):
                    company = job.get('company', 'Unknown')
                    title = job.get('title', 'Unknown')
                    duration = job.get('duration_years', 0)
                    debug_log(f"  {i}. {company} - {title} ({duration} years)")

        # Safely log skill experience details
        skill_exp = resume_info.get('skill_experience', {})
        if isinstance(skill_exp, dict):
            debug_log(f"Skill experience details:")
            for skill_name, exp_data in list(skill_exp.items())[:6]:  # Log first 6
                if isinstance(exp_data, dict):
                    total_yrs = exp_data.get('total_years', 0)
                    proj_count = len(exp_data.get('projects', []))
                    debug_log(f"  {skill_name}: {total_yrs} years across {proj_count} projects")

        return resume_info

    except json.JSONDecodeError as e:
        log(f"[RESUME_ANALYZE] ❌ Failed to parse JSON: {str(e)}")
        log(f"[RESUME_ANALYZE] Raw response length: {len(raw)}")
        debug_log(f"Raw response:\n{raw[:2000]}")
        raise


def score_skill_match(resume_info: dict, jd_req: dict) -> dict:
    """Score skill matching with skill-specific experience comparison"""
    log("[SKILL_MATCH] Scoring skill matches with experience validation...")

    resume_skills = resume_info.get('skills', [])
    skill_experience = resume_info.get('skill_experience', {})
    core_skills = jd_req.get('core_skills', [])
    secondary_skills = jd_req.get('secondary_skills', [])

    all_jd_skills = core_skills + secondary_skills

    debug_log(f"Resume skills count: {len(resume_skills) if isinstance(resume_skills, list) else 'not a list'}")
    debug_log(f"Skills with experience data: {len(skill_experience) if isinstance(skill_experience, dict) else 0}")
    debug_log(f"Required skills count: {len(all_jd_skills)}")

    prompt = f"""
Score how well resume skills match job requirements, considering skill-specific experience.

Resume Skills: {json.dumps(resume_skills)}

Skill-Specific Experience from Resume:
{json.dumps(skill_experience, indent=2)[:4000]}

Required Skills from JD:
{json.dumps(all_jd_skills)}

For each required skill:
1. Check if skill is present in resume (including variants)
2. Find the skill_experience data for that skill
3. Compare years_found against min_years required
4. Rate evidence strength based on project details

Return ONLY valid JSON, no markdown, no extra text:
{{
  "core_skill_matches": [
    {{
      "skill": "",
      "matched": true,
      "evidence_strength": "strong",
      "years_found": 0,
      "years_required": 0,
      "meets_years_requirement": true,
      "projects_used_in": ["company1", "company2"]
    }}
  ],
  "matched_core_count": 0,
  "total_core_count": 0,
  "core_match_percentage": 0
}}

IMPORTANT: Use the skill_experience data to populate years_found and projects_used_in accurately.
Return ONLY the JSON, nothing else.
"""

    raw = invoke_claude(prompt, max_tokens=3000)

    try:
        # Extract JSON from response
        json_text = extract_json_from_text(raw)
        debug_log(f"Extracted JSON text ({len(json_text)} chars)")

        skill_match = json.loads(json_text)
        log(f"[SKILL_MATCH] ✅ Matched {skill_match.get('matched_core_count', 0)}/{skill_match.get('total_core_count', 0)} core skills")
        log(f"[SKILL_MATCH] ✅ Match percentage: {skill_match.get('core_match_percentage', 0)}%")

        # Log details for each skill
        matches_list = skill_match.get('core_skill_matches', [])
        if isinstance(matches_list, list):
            for match in matches_list[:5]:  # Log first 5
                if isinstance(match, dict):
                    skill = match.get('skill', '')
                    yrs_found = match.get('years_found', 0)
                    yrs_req = match.get('years_required', 0)
                    meets = match.get('meets_years_requirement', False)
                    debug_log(f"  {skill}: {yrs_found}y found (needs {yrs_req}y) - {'✓' if meets else '✗'}")

        return skill_match

    except json.JSONDecodeError as e:
        log(f"[SKILL_MATCH] ❌ Failed to parse JSON: {str(e)}")
        log(f"[SKILL_MATCH] Raw response length: {len(raw)}")
        debug_log(f"Raw response:\n{raw[:2000]}")
        raise


def calculate_final_score(resume_info: dict, jd_req: dict, skill_match: dict) -> dict:
    """Calculate final score with experience-weighted skill matching"""
    log("[FINAL_SCORE] Calculating final score...")

    # Core skills score (60% weight) - now includes experience matching
    core_match_pct = skill_match.get('core_match_percentage', 0)
    core_score = core_match_pct / 100.0
    debug_log(f"Core match: {core_match_pct}% -> score: {core_score:.4f}")

    # Experience score (25% weight) - overall experience
    req_years = jd_req.get('experience_requirements', {}).get('total_years', 0)
    resume_years = resume_info.get('total_experience_years', 0)

    if resume_years >= req_years:
        exp_score = 1.0
    else:
        exp_score = max(0.0, 1.0 - (req_years - resume_years) * 0.10)

    debug_log(f"Experience: {resume_years} years (required: {req_years}) -> score: {exp_score:.4f}")

    # Additional factors (15% weight)
    additional_score = 0.0
    certs = resume_info.get('certifications', [])
    projects = resume_info.get('projects', [])

    has_certs = isinstance(certs, list) and len(certs) > 0
    has_projects = isinstance(projects, list) and len(projects) > 0

    if has_certs:
        additional_score += 0.5
    if has_projects:
        additional_score += 0.5

    debug_log(f"Additional: certs={has_certs} projects={has_projects} -> score: {additional_score:.4f}")

    # Final calculation: 60% core + 25% experience + 15% additional
    overall = (core_score * 0.60) + (exp_score * 0.25) + (additional_score * 0.15)
    overall_percentage = int(round(overall * 100))

    log(f"[FINAL_SCORE] ✅ Core: {core_score:.4f} (60%)")
    log(f"[FINAL_SCORE] ✅ Experience: {exp_score:.4f} (25%)")
    log(f"[FINAL_SCORE] ✅ Additional: {additional_score:.4f} (15%)")
    log(f"[FINAL_SCORE] ✅ Overall: {overall_percentage}/100")

    return {
        "overall_score": overall_percentage,
        "breakdown": {
            "core_skills_score": round(core_score * 100, 2),
            "experience_score": round(exp_score * 100, 2),
            "additional_score": round(additional_score * 100, 2)
        },
        "core_skill_matches": skill_match.get('core_skill_matches', []),
        "matched_core_skills": skill_match.get('matched_core_count', 0),
        "total_core_skills": skill_match.get('total_core_count', 0),
        "resume_years": resume_years,
        "required_years": req_years
    }


def save_scoring_result(s3_key: str, jd_id: int, jd_text: str, jd_req: dict, result: dict):
    """Save scoring result to database"""
    log("[DB_SAVE] Saving scoring result...")

    try:
        with pg_conn() as conn, conn.cursor() as cur:
            query = """
                INSERT INTO resume_data.resume_scores (
                    s3_key, jd_id, jd_text, jd_requirements, 
                    overall_score, scoring_details, created_at
                )
                VALUES (%s, %s, %s, %s::jsonb, %s, %s::jsonb, %s)
            """

            debug_log("Executing INSERT query")
            debug_log(f"s3_key={s3_key}")
            debug_log(f"jd_id={jd_id}")
            debug_log(f"overall_score={result['overall_score']}")

            cur.execute(query, (
                s3_key, jd_id, jd_text, json.dumps(jd_req),
                result['overall_score'], json.dumps(result), datetime.utcnow()
            ))

        log("[DB_SAVE] ✅ Saved scoring result")

    except Exception as e:
        log(f"[DB_SAVE] ⚠️ Could not save result: {str(e)}")
        debug_log(traceback.format_exc())


def lambda_handler(event, context):
    """Lambda handler"""
    log("\n" + "=" * 80)
    log("[LAMBDA] Resume Scoring Lambda - With Complete Work Experience Extraction")
    log(f"[LAMBDA] Time: {datetime.utcnow().isoformat()}Z")
    log(f"[LAMBDA] Region: {os.environ.get('AWS_REGION', 'us-east-1')}")
    log(f"[LAMBDA] Debug: {DEBUG}")
    log("=" * 80)

    debug_log(f"Event: {json.dumps(event, indent=2, default=str)}")

    try:
        # Parse event
        if 'Records' in event:
            log("[INPUT] Event type: S3 trigger")
            s3_bucket = event['Records'][0]['s3']['bucket']['name']
            s3_key = unquote_plus(event['Records'][0]['s3']['object']['key'])
            jd_id = event.get('jd_id', 1)
        else:
            log("[INPUT] Event type: Direct invocation")
            s3_bucket = event.get('s3_bucket')
            s3_key = event.get('s3_key')
            jd_id = event.get('jd_id', 1)

        if not all([s3_bucket, s3_key, jd_id]):
            log("[INPUT] ❌ Missing required parameters")
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'error': 'Missing required parameters: s3_bucket, s3_key, jd_id'
                })
            }

        log(f"[INPUT] s3_bucket={s3_bucket}")
        log(f"[INPUT] s3_key={s3_key}")
        log(f"[INPUT] jd_id={jd_id}")

        # Step 1: Read resume from S3
        log("\n" + "-" * 80)
        log("[STEP 1] Reading resume from S3...")
        resume_text = ResumeReader.read_from_s3(s3_bucket, s3_key)
        log(f"[STEP 1] ✅ Resume loaded: {len(resume_text)} chars")

        # Step 2: Get JD from database
        log("\n" + "-" * 80)
        log("[STEP 2] Getting job description from database...")
        jd_row = get_job_description(jd_id)
        if not jd_row:
            log("[STEP 2] ❌ JD not found")
            return {
                'statusCode': 404,
                'body': json.dumps({
                    'error': f'Job description not found for ID: {jd_id}'
                })
            }

        jd_text = jd_row.get('description', '')
        log(f"[STEP 2] ✅ JD loaded: {len(jd_text)} chars")

        # Step 3: Extract JD requirements using Claude
        log("\n" + "-" * 80)
        log("[STEP 3] Extracting JD requirements using Claude...")
        jd_req = extract_jd_requirements(jd_text)
        log("[STEP 3] ✅ JD requirements extracted")

        # Step 4: Analyze resume using Claude with complete job extraction
        log("\n" + "-" * 80)
        log("[STEP 4] Analyzing resume with COMPLETE work history extraction...")
        resume_info = analyze_resume_with_claude(resume_text)
        log("[STEP 4] ✅ Resume analyzed with all jobs and skill experience data")

        # Step 5: Score skill match using Claude
        log("\n" + "-" * 80)
        log("[STEP 5] Scoring skill matches with experience validation...")
        skill_match = score_skill_match(resume_info, jd_req)
        log("[STEP 5] ✅ Skill matches scored")

        # Step 6: Calculate final score
        log("\n" + "-" * 80)
        log("[STEP 6] Calculating final score...")
        result = calculate_final_score(resume_info, jd_req, skill_match)
        log("[STEP 6] ✅ Final score calculated")

        # Step 7: Save to database
        log("\n" + "-" * 80)
        log("[STEP 7] Saving results to database...")
        save_scoring_result(s3_key, jd_id, jd_text, jd_req, result)
        log("[STEP 7] ✅ Results saved")

        # Prepare response
        skills = resume_info.get('skills', [])
        certs = resume_info.get('certifications', [])
        skill_exp = resume_info.get('skill_experience', {})
        jobs = resume_info.get('work_experience', [])

        payload = {
            "success": True,
            "s3_key": s3_key,
            "jd_id": jd_id,
            "jd_title": jd_row.get('title'),
            "overall_score": result['overall_score'],
            "breakdown": result['breakdown'],
            "core_skill_matches": result['core_skill_matches'],
            "resume_info": {
                "skills_count": len(skills) if isinstance(skills, list) else 0,
                "total_experience_years": resume_info.get('total_experience_years', 0),
                "jobs_extracted": len(jobs) if isinstance(jobs, list) else 0,
                "skills_with_experience_data": len(skill_exp) if isinstance(skill_exp, dict) else 0,
                "certifications": certs if isinstance(certs, list) else [],
                "projects_count": len(resume_info.get('projects', [])) if isinstance(resume_info.get('projects', []),
                                                                                     list) else 0
            },
            "timestamp": datetime.utcnow().isoformat()
        }

        log("\n" + "=" * 80)
        log(f"[SUCCESS] ✅ Overall Score: {result['overall_score']}/100")
        log(f"[SUCCESS] ✅ Jobs Extracted: {len(jobs) if isinstance(jobs, list) else 0}")
        log("=" * 80)

        return {
            'statusCode': 200,
            'body': json.dumps(payload, indent=2, default=str)
        }

    except Exception as e:
        err = {"error": str(e), "traceback": traceback.format_exc()}
        log(f"\n[ERROR] ❌ {str(e)}")
        log(f"[ERROR] Traceback:\n{traceback.format_exc()}")
        return {
            'statusCode': 500,
            'body': json.dumps(err)
        }