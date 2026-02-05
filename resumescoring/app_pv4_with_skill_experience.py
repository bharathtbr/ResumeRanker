"""
Enhanced Resume Scoring Lambda - Combines Vector Search + Pre-Extracted Skill Experience
=========================================================================================

Based on: app_pv3.py
Added: Pre-extracted skill experience from parsing

This version:
1. ✅ KEEPS all vector search for evidence (from app_pv3.py)
2. ✅ KEEPS Claude grading of chunks (from app_pv3.py)  
3. ✅ ADDS pre-extracted skill experience (total years, jobs breakdown)
4. ✅ COMBINES both for final scoring

Best of both worlds!
"""

import os, json, boto3, math, re, uuid, traceback, hashlib
from datetime import datetime
import html
import psycopg2
import psycopg2.extras
from botocore.exceptions import ClientError

# =========================
# ENV
# =========================
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

VECTOR_BUCKET = os.getenv("VECTOR_BUCKET")
VECTOR_INDEX  = os.getenv("VECTOR_INDEX")

DB_NAME = os.getenv("PG_DB", "resumes")
DB_USER = os.getenv("PG_USER", "")
DB_PASS = os.getenv("PG_PASS", "")
DB_HOST = os.getenv("PG_HOST", "")
DB_PORT = os.getenv("PG_PORT", "5432")

BEDROCK_EMBED_MODEL = os.getenv("BEDROCK_EMBED_MODEL", "amazon.titan-embed-text-v2:0")
BEDROCK_LLM_MODEL   = os.getenv("BEDROCK_LLM_MODEL", "us.anthropic.claude-3-5-sonnet-20241022-v2:0")

# Debug tuning
LOG_EVENT_CHARS  = int(os.getenv("LOG_EVENT_CHARS", "6000"))
LOG_PROMPT_CHARS = int(os.getenv("LOG_PROMPT_CHARS", "1400"))
LOG_CLAUDE_CHARS = int(os.getenv("LOG_CLAUDE_CHARS", "1600"))
LOG_CHUNK_CHARS  = int(os.getenv("LOG_CHUNK_CHARS", "400"))
LOG_S3V_SAMPLE   = int(os.getenv("LOG_S3V_SAMPLE", "10"))

EVIDENCE_TOPK       = int(os.getenv("EVIDENCE_TOPK", "99"))
EVIDENCE_THRESHOLD  = float(os.getenv("EVIDENCE_THRESHOLD", "0.05"))

bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)
s3vector = boto3.client("s3vectors", region_name=AWS_REGION)

# =========================
# SKILL VARIANTS (for matching)
# =========================

SKILL_VARIANTS_MAP = {
    ".NET": [".NET", ".Net", "dotnet", "dot net", "ASP.NET", "C#", "VB.NET"],
    "AWS Lambda": ["AWS Lambda", "Lambda", "Lambda functions"],
    "AWS EC2": ["AWS EC2", "EC2", "Amazon EC2"],
    "Azure Functions": ["Azure Functions", "Azure Function"],
    "React": ["React", "React.js", "ReactJS", "Redux"],
    "Angular": ["Angular", "AngularJS"],
}

def normalize_skill_name(skill_name: str) -> str:
    """Normalize skill name."""
    skill_lower = skill_name.lower().strip()
    
    for canonical, variants in SKILL_VARIANTS_MAP.items():
        if skill_lower in [v.lower() for v in variants]:
            return canonical
    
    return skill_name

# =========================
# Helpers (SAME AS app_pv3.py)
# =========================
def log(msg: str):
    print(msg)

def preview(s: str, n: int):
    if s is None:
        return ""
    s = str(s)
    return s[:n] + ("..." if len(s) > n else "")

def sha1_hex(s: str) -> str:
    return hashlib.sha1((s or "").encode("utf-8")).hexdigest()

def canonical_resume_id(s3_key: str) -> str:
    s3_key = html.unescape(s3_key)  # &amp; → &
    return sha1_hex(s3_key)

def pg_conn():
    return psycopg2.connect(dbname=DB_NAME, user=DB_USER, password=DB_PASS, host=DB_HOST, port=DB_PORT)

# =========================
# Bedrock (SAME AS app_pv3.py)
# =========================
def invoke_claude(prompt: str, max_tokens: int = 900) -> str:
    log(f"[CLAUDE] model={BEDROCK_LLM_MODEL} max_tokens={max_tokens}")
    log(f"[CLAUDE] prompt preview:\n{preview(prompt, LOG_PROMPT_CHARS)}")

    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0
    }

    resp = bedrock.invoke_model(modelId=BEDROCK_LLM_MODEL, body=json.dumps(body))
    result = json.loads(resp["body"].read())
    text = (result.get("content", [{}])[0].get("text") or "").strip()

    log(f"[CLAUDE] raw chars={len(text)} preview:\n{preview(text, LOG_CLAUDE_CHARS)}")

    if "```" in text:
        parts = text.split("```")
        text = max(parts, key=len).strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()

    return text.strip()

def get_embedding(text: str):
    q = (text or "")[:8000]
    log(f"[EMBED] model={BEDROCK_EMBED_MODEL} text_preview={preview(q, 120)}")

    resp = bedrock.invoke_model(
        modelId=BEDROCK_EMBED_MODEL,
        body=json.dumps({"inputText": q}),
        accept="application/json",
        contentType="application/json"
    )
    emb = json.loads(resp["body"].read())["embedding"]
    log(f"[EMBED] ✅ dims={len(emb)}")
    return emb

# =========================
# Similarity (SAME AS app_pv3.py)
# =========================
def to_similarity(result_item: dict, metric: str) -> float:
    if not result_item:
        return 0.0

    if result_item.get("score") is not None:
        try:
            s = float(result_item["score"])
            if s != s:
                return 0.0
            return max(0.0, min(1.0, s))
        except:
            return 0.0

    dist = result_item.get("distance")
    if dist is None:
        return 0.0

    try:
        d = float(dist)
        if d != d:
            return 0.0
    except:
        return 0.0

    m = (metric or "").lower()

    if "cos" in m:
        sim = 1.0 - d
        return max(0.0, min(1.0, sim))

    if "l2" in m or "euc" in m:
        return 1.0 / (1.0 + d)

    sim = 1.0 - d
    return max(0.0, min(1.0, sim))

# =========================
# JD extraction (SAME AS app_pv3.py)
# =========================
def extract_jd_requirements(jd_text: str) -> dict:
    jd_text = (jd_text or "")[:20000]

    prompt = f"""
Extract requirements from this Job Description.
Return ONLY JSON.

JD:
{jd_text}

Return:
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
"""
    raw = invoke_claude(prompt, max_tokens=2500)
    jd = json.loads(raw)
    log(f"[JD] ✅ job_title={jd.get('job_title')} core={len(jd.get('core_skills', []))}")
    return jd

# =========================
# Postgres (ENHANCED - reads skill_experience_json)
# =========================
def get_resume_profile(resume_id: str) -> dict:
    log(f"[PG] load resume_profiles resume_id={resume_id}")
    with pg_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM resume_data.resume_profiles WHERE resume_id=%s", (resume_id,))
        row = cur.fetchone()
        if not row:
            log("[PG] ❌ resume not found")
            return None
        row = dict(row)
        log(f"[PG] ✅ found name={row.get('name')} years={row.get('years_exp')} skills_count={len(row.get('skills_flat') or [])}")
        
        # Check for pre-extracted skill experience
        if row.get("skill_experience_json"):
            skill_exp_count = len(row["skill_experience_json"])
            log(f"[PG] ✅ skill_experience_json: {skill_exp_count} skills with work evidence")
        else:
            log(f"[PG] ⚠️ No skill_experience_json (resume parsed before this feature)")
        
        return row

def get_chunk_text_by_vector_key(vector_key: str) -> str:
    """SAME AS app_pv3.py"""
    log(f"[PG] load chunk_text by vector_key={vector_key}")
    if not vector_key:
        return ""
    with pg_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT chunk_text FROM resume_data.resume_chunks WHERE vector_key=%s LIMIT 1", (vector_key,))
        row = cur.fetchone()
        if not row:
            log("[PG] ❌ chunk not found for vector_key")
            return ""
        text = row[0] or ""
        log(f"[PG] ✅ chunk chars={len(text)} preview={preview(text, 250)}")
        return text

# =========================
# S3 Vectors (SAME AS app_pv3.py)
# =========================
def _extract_results(resp: dict):
    if not isinstance(resp, dict):
        log("[S3V][EXTRACT] ❌ resp is not dict")
        return [], "cosine"

    keys = list(resp.keys())
    metric = (resp.get("distanceMetric") or resp.get("distance_metric") or "cosine").lower()

    log(f"[S3V][EXTRACT] response keys={keys}")
    log(f"[S3V][EXTRACT] distanceMetric={metric}")

    results = resp.get("matches") or resp.get("results") or resp.get("vectors") or []
    log(f"[S3V][EXTRACT] results_count={len(results)}")

    for i, r in enumerate(results[:LOG_S3V_SAMPLE]):
        md = r.get("metadata", {}) or {}
        log(
            f"[S3V][EXTRACT] #{i} key={r.get('key')} "
            f"score={r.get('score')} distance={r.get('distance')} "
            f"type={md.get('type')} resume_id={md.get('resume_id')} page={md.get('page')} chunk_index={md.get('chunk_index')}"
        )

    return results, metric

def _query_best(resume_id: str, query_text: str) -> dict:
    """SAME AS app_pv3.py"""
    q_emb = get_embedding(query_text)

    log(f"[S3V][QUERY] bucket={VECTOR_BUCKET} index={VECTOR_INDEX} topK={EVIDENCE_TOPK} region={AWS_REGION}")
    if not VECTOR_BUCKET or not VECTOR_INDEX:
        raise ValueError(f"Missing VECTOR_BUCKET/VECTOR_INDEX bucket={VECTOR_BUCKET} index={VECTOR_INDEX}")

    try:
        resp = s3vector.query_vectors(
            vectorBucketName=VECTOR_BUCKET,
            indexName=VECTOR_INDEX,
            queryVector={"float32": q_emb},
            topK=EVIDENCE_TOPK,
            returnMetadata=True,
            returnDistance=True,
        )
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code")
        msg = e.response.get("Error", {}).get("Message")
        log(f"[S3V][ERROR] code={code} msg={msg}")
        raise

    results, metric = _extract_results(resp)

    sample_ids = [(r.get("metadata", {}) or {}).get("resume_id") for r in results[:10]]
    log(f"[S3V] sample resume_ids={sample_ids}")

    best = None
    best_sim = 0.0
    matched = 0

    for r in results:
        md = r.get("metadata", {}) or {}
        if md.get("type") != "content":
            continue
        if md.get("resume_id") != resume_id:
            continue

        matched += 1
        sim = to_similarity(r, metric)

        log(
            f"[S3V][CAND] key={r.get('key')} "
            f"distance={r.get('distance')} score={r.get('score')} "
            f"sim={sim:.4f} metric={metric}"
        )

        if sim > best_sim:
            best_sim = sim
            best = {
                "similarity": best_sim,
                "vector_key": r.get("key",""),
                "page": md.get("page",""),
                "chunk_index": md.get("chunk_index",""),
            }

    log(f"[S3V] matched_this_resume={matched} best_similarity={best_sim:.4f} metric={metric}")
    if best:
        log(f"[S3V] ✅ best vector_key={best.get('vector_key')} page={best.get('page')} chunk_index={best.get('chunk_index')}")
    return best or {"similarity": 0.0, "vector_key": "", "page": "", "chunk_index": ""}

def best_chunk_for_skill(resume_id: str, skill_obj: dict) -> dict:
    """SAME AS app_pv3.py"""
    name = skill_obj["name"]
    variants = skill_obj.get("variants") or [name]

    semantic_q = (
        f"Resume evidence of hands-on professional experience with {name}. "
        f"Related terms: {', '.join(variants)}. "
        f"Look for responsibilities, projects, production systems."
    )
    literal_q = f"{name} " + " ".join(variants)

    log("\n" + "-"*80)
    log(f"[EVIDENCE] skill={name}")
    log(f"[EVIDENCE] semantic_q={preview(semantic_q, 220)}")
    log(f"[EVIDENCE] literal_q={preview(literal_q, 220)}")

    best1 = _query_best(resume_id, semantic_q)
    best2 = _query_best(resume_id, literal_q)
    log(f"[EVIDENCE] best1 best_similarity={best1.get('similarity'):.4f} vector_key={best1.get('vector_key')}")
    log(f"[EVIDENCE] best2 best_similarity={best2.get('similarity'):.4f} vector_key={best2.get('vector_key')}")
    picked = best1 if best1["similarity"] >= best2["similarity"] else best2
    log(f"[EVIDENCE] picked best_similarity={picked.get('similarity'):.4f} vector_key={picked.get('vector_key')}")
    return picked

# =========================
# Claude Evidence Grading (SAME AS app_pv3.py)
# =========================
def grade_skill_evidence(skill_obj: dict, chunk_text: str) -> dict:
    """SAME AS app_pv3.py"""
    name = skill_obj["name"]
    min_years = int(skill_obj.get("min_years") or 0)

    prompt = f"""
You are grading resume evidence for a job requirement.

Skill: {name}
Minimum years required: {min_years}

Resume excerpt:
{chunk_text}

Return ONLY JSON:
{{
  "has_skill": true/false,
  "evidence_strength": "strong|moderate|weak|none",
  "years_supported": 0,
  "meets_years": true/false,
  "why": "one sentence",
  "quote": "exact short quote from excerpt (<=25 words)",
  "confidence": 0.0
}}

Guidance:
- strong: clearly used in work/projects/responsibilities
- moderate: used but details limited
- weak: just listed / mentioned
- none: not supported by excerpt
"""
    raw = invoke_claude(prompt, max_tokens=900)
    data = json.loads(raw)
    log(f"[GRADE] {name} strength={data.get('evidence_strength')} meets_years={data.get('meets_years')} conf={data.get('confidence')}")
    return data

# =========================
# NEW: Get Pre-Extracted Skill Experience
# =========================
# =========================
# NEW: Get Pre-Extracted Skill Experience with Intelligent Matching
# =========================
def get_skill_experience_from_profile(skill_experience_json: dict, skill_name: str, min_years: int = 0) -> dict:
    """
    Get pre-extracted skill experience with intelligent variant matching.

    Uses Claude to determine which extracted skills should count toward the requirement.

    Example:
    - JD asks for ".NET" (generic) → Includes .NET 6, .NET 7, ASP.NET, C#, etc.
    - JD asks for ".NET 6" (specific) → Only .NET 6 experience
    - JD asks for "React" → Includes React, React.js, Redux
    """

    if not skill_experience_json:
        return {"total_years": 0.0, "jobs_using_skill": []}

    # Try exact match first (fast path)
    if skill_name in skill_experience_json:
        return skill_experience_json[skill_name]

    # Try case-insensitive match (fast path)
    skill_lower = skill_name.lower()
    for key, value in skill_experience_json.items():
        if key.lower() == skill_lower:
            return value

    # If no exact match, use Claude to intelligently match variants
    print(f"[SKILL_MATCH] No exact match for '{skill_name}', using intelligent matching...")

    available_skills = list(skill_experience_json.keys())
    available_skills_str = ", ".join(available_skills[:50])  # Limit to first 50

    prompt = f"""Given a job requirement and a list of skills from a resume, determine which resume skills should count toward the requirement.

Job Requirement: "{skill_name}" with {min_years}+ years experience

Available Resume Skills: {available_skills_str}

Rules:
1. If requirement is GENERIC (e.g., ".NET", "React"), include ALL variants
   - ".NET" requirement → include: .NET 6, .NET 7, ASP.NET, C#, Entity Framework
   - "React" requirement → include: React, React.js, ReactJS, Redux

2. If requirement is SPECIFIC (e.g., ".NET 6", "React 18"), ONLY include that version
   - ".NET 6" requirement → ONLY .NET 6 (not .NET 7, not generic .NET)
   - "React 18" requirement → ONLY React 18

3. If requirement is for framework subset (e.g., "ASP.NET"), include that + related
   - "ASP.NET" → include ASP.NET, ASP.NET Core, Web API

Return ONLY a JSON array of matching skill names:
["skill1", "skill2", ...]

If no matches, return empty array: []
"""

    try:
        raw = invoke_claude(prompt, max_tokens=500)

        # Clean response
        raw = raw.strip()
        if raw.startswith("```json"):
            raw = raw[7:]
        elif raw.startswith("```"):
            raw = raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

        matching_skills = json.loads(raw)

        if not matching_skills or not isinstance(matching_skills, list):
            print(f"[SKILL_MATCH] No matches found for '{skill_name}'")
            return {"total_years": 0.0, "jobs_using_skill": []}

        print(f"[SKILL_MATCH] Matched '{skill_name}' to: {matching_skills}")

        # Aggregate experience from all matching skills
        all_jobs = []
        seen_companies = set()

        for matched_skill in matching_skills:
            if matched_skill in skill_experience_json:
                skill_data = skill_experience_json[matched_skill]
                jobs = skill_data.get("jobs_using_skill", [])

                # Deduplicate by company (take longest duration if same company)
                for job in jobs:
                    company = job.get("company", "")
                    if company and company not in seen_companies:
                        seen_companies.add(company)
                        all_jobs.append({
                            **job,
                            "matched_from_skill": matched_skill  # Track which skill this came from
                        })

        # Calculate total years
        total_months = 0
        for job in all_jobs:
            months = job.get("duration_months")
            if months is not None:
                total_months += int(months)

        total_years = round(total_months / 12.0, 1)

        print(f"[SKILL_MATCH] Total experience for '{skill_name}': {total_years}y from {len(all_jobs)} jobs")

        return {
            "total_years": total_years,
            "jobs_using_skill": all_jobs,
            "matched_skills": matching_skills  # Track which skills contributed
        }

    except Exception as e:
        print(f"[SKILL_MATCH] Error matching '{skill_name}': {e}")
        traceback.print_exc()
        return {"total_years": 0.0, "jobs_using_skill": []}
# =========================
# ENHANCED SCORING (Combines Vector Search + Pre-Extracted Experience)
# =========================

def cosine_similarity(a, b) -> float:
    """SAME AS app_pv3.py"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x*y for x, y in zip(a, b))
    ma = math.sqrt(sum(x*x for x in a))
    mb = math.sqrt(sum(y*y for y in b))
    if ma == 0 or mb == 0:
        return 0.0
    return max(0.0, min(1.0, dot/(ma*mb)))

def score_resume(resume: dict, jd_req: dict) -> dict:
    """
    ENHANCED: Combines vector search evidence + pre-extracted skill experience.
    
    For each skill:
    1. Find best chunk (vector search) ✅ FROM app_pv3.py
    2. Grade chunk evidence (Claude) ✅ FROM app_pv3.py
    3. Get pre-extracted experience (NEW!)
    4. Combine both for final scoring
    """
    
    resume_id = resume["resume_id"]
    skills_flat = resume.get("skills_flat") or []
    skill_experience_json = resume.get("skill_experience_json") or {}  # NEW
    
    skills_text = ", ".join(map(str, skills_flat))[:6000]

    jd_names = [s["name"] for s in jd_req.get("core_skills", [])] + [s["name"] for s in jd_req.get("secondary_skills", [])]
    jd_skill_text = ", ".join(jd_names)[:6000]

    log(f"[SCORE] resume_id={resume_id} skills_count={len(skills_flat)} core={len(jd_req.get('core_skills', []))}")
    log(f"[SCORE] skill_experience_json: {len(skill_experience_json)} skills")

    # Semantic score (SAME AS app_pv3.py)
    sem_a = get_embedding(f"Job required skills: {jd_skill_text}")
    sem_b = get_embedding(f"Candidate skills: {skills_text}")
    skills_sem = cosine_similarity(sem_a, sem_b)
    log(f"[SCORE] skills_semantic={skills_sem:.4f}")

    # Core skills scoring (ENHANCED)
    core = jd_req.get("core_skills", [])
    core_points = 0.0
    core_results = []

    for skill_obj in core:
        skill_name = skill_obj["name"]
        min_years = int(skill_obj.get("min_years") or 0)
        
        log(f"\n[SKILL_SCORE] {skill_name} (requires {min_years}+ years)")
        
        # STEP 1: Find best chunk (FROM app_pv3.py)
        best = best_chunk_for_skill(resume_id, skill_obj)
        vector_key = best.get("vector_key","")
        chunk_text = get_chunk_text_by_vector_key(vector_key)
        
        # STEP 2: Grade chunk evidence (FROM app_pv3.py)
        if best["similarity"] < EVIDENCE_THRESHOLD or not chunk_text.strip():
            chunk_evidence = {
                "has_skill": False,
                "evidence_strength": "none",
                "years_supported": 0,
                "meets_years": False,
                "why": "No supporting evidence found",
                "quote": "",
                "confidence": 0.0
            }
            log(f"[CHUNK_EVIDENCE] {skill_name} ❌ no evidence")
        else:
            chunk_evidence = grade_skill_evidence(skill_obj, chunk_text)
            log(f"[CHUNK_EVIDENCE] {skill_name} strength={chunk_evidence.get('evidence_strength')}")
        
        # STEP 3: Get pre-extracted experience (NEW!)
        skill_exp = get_skill_experience_from_profile(skill_experience_json, skill_name)
        total_years = skill_exp.get("total_years", 0.0)
        jobs_breakdown = skill_exp.get("jobs_using_skill", [])
        
        log(f"[PRE_EXTRACTED] {skill_name}: {total_years}y across {len(jobs_breakdown)} jobs")
        
        # STEP 4: Combine both for final evaluation
        # Use chunk evidence for strength, but pre-extracted for years

        # STEP 4: Combine both for final evaluation
        # Use chunk evidence for strength, but pre-extracted for years

        if total_years > 0:
            # We have pre-extracted data - use it for years
            meets_years_requirement = total_years >= min_years

            # FIX: Handle None in duration_months
            jobs_breakdown_fixed = []
            for j in jobs_breakdown:
                months = j.get("duration_months")
                if months is None:
                    months = 0

                jobs_breakdown_fixed.append({
                    "company": j.get("company", ""),
                    "years": round(int(months) / 12.0, 1),
                    "evidence": j.get("evidence", "")[:150]
                })

            final_evidence = {
                "has_skill": True,
                "evidence_strength": chunk_evidence.get("evidence_strength", "moderate"),
                "years_supported": int(total_years),
                "total_years": total_years,  # NEW: actual total
                "jobs_breakdown": jobs_breakdown_fixed,  # FIXED
                "meets_years": meets_years_requirement,
                "why": chunk_evidence.get("why", ""),
                "quote": chunk_evidence.get("quote", ""),
                "confidence": chunk_evidence.get("confidence", 0.8)
            }
            log(f"[COMBINED] {skill_name}: Using pre-extracted {total_years}y + chunk evidence")
        else:
            # No pre-extracted data - fall back to chunk evidence only
            final_evidence = chunk_evidence
            final_evidence["total_years"] = chunk_evidence.get("years_supported", 0)
            final_evidence["jobs_breakdown"] = []
            log(f"[COMBINED] {skill_name}: No pre-extracted data, using chunk evidence only")
        
        # Calculate points
        strength = final_evidence.get("evidence_strength", "none")
        meets_years = final_evidence.get("meets_years", False)
        
        if strength == "strong":
            pts = 1.0
        elif strength == "moderate":
            pts = 0.7
        elif strength == "weak":
            pts = 0.3
        else:
            pts = 0.0
        
        if min_years > 0 and not meets_years:
            pts = min(pts, 0.4)
        
        core_points += pts
        log(f"[FINAL_SCORE] {skill_name}: {pts:.2f} points (strength={strength}, meets_years={meets_years})")
        
        core_results.append({
            "skill": skill_name,
            "min_years": min_years,
            "best_similarity": round(best.get("similarity", 0.0), 4),
            "vector_key": vector_key,
            "page": best.get("page",""),
            "chunk_index": best.get("chunk_index",""),
            "evidence": final_evidence
        })

    core_score = core_points / (len(core) if core else 1.0)

    # Experience score (SAME AS app_pv3.py)
    req_years = int(jd_req.get("experience_requirements", {}).get("total_years") or 0)
    res_years = int(resume.get("years_exp") or 0)
    exp_score = 1.0 if res_years >= req_years else max(0.0, 1.0 - (req_years - res_years)*0.10)

    # Final score (SAME AS app_pv3.py)
    final = 0.60 * core_score + 0.15 * skills_sem + 0.25 * exp_score
    overall = int(round(final * 100))

    log(f"[SCORE] ✅ core={core_score:.4f} sem={skills_sem:.4f} exp={exp_score:.4f} overall={overall}")

    return {
        "overall_score": overall,
        "breakdown": {
            "core_evidence_score": round(core_score, 4),
            "skills_semantic_score": round(skills_sem, 4),
            "experience_score": round(exp_score, 4),
        },
        "core_skill_evidence": core_results,
        "resume_info": {
            "resume_id": resume_id,
            "file_name": resume.get("file_name",""),
            "s3_key": resume.get("s3_key",""),
            "name": resume.get("name",""),
            "title": resume.get("title",""),
            "years_exp": resume.get("years_exp",""),
            "email": resume.get("email",""),
            "phone": resume.get("phone",""),
        }
    }

# =========================
# Agent Response (SAME AS app_pv3.py)
# =========================
def agent_response(event, payload: dict):
    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": event.get("actionGroup", ""),
            "function": event.get("function", ""),
            "functionResponse": {
                "responseBody": {
                    "TEXT": {"body": json.dumps(payload, indent=2)}
                }
            }
        }
    }

# =========================
# Handler (SAME AS app_pv3.py)
# =========================
def lambda_handler(event, context):
    log("\n" + "="*90)
    log("[MATCH] handler invoked - ENHANCED with pre-extracted skill experience")
    log(f"[MATCH] time={datetime.utcnow().isoformat()}Z region={AWS_REGION}")
    log("="*90)
    log("[MATCH] event preview:\n" + preview(json.dumps(event), LOG_EVENT_CHARS))

    try:
        if not VECTOR_BUCKET or not VECTOR_INDEX:
            raise ValueError(f"Missing VECTOR_BUCKET/VECTOR_INDEX bucket={VECTOR_BUCKET} index={VECTOR_INDEX}")

        s3_key = None
        jd_text = None
        is_agent = ("messageVersion" in event and "function" in event)

        if is_agent:
            params = event.get("parameters", [])
            s3_key = next((p["value"] for p in params if p.get("name") == "resume_name"), None)
            jd_text = next((p["value"] for p in params if p.get("name") == "job_description"), None)

        if not s3_key:
            s3_key = event.get("s3_key") or event.get("resume_name")
        if not jd_text:
            jd_text = event.get("job_description")

        if not s3_key or not jd_text:
            raise ValueError("Missing inputs: need resume_name (s3_key) + job_description")

        resume_id = canonical_resume_id(s3_key)

        log(f"[INPUT] s3_key={s3_key}")
        log(f"[INPUT] resume_id(sha1)={resume_id}")
        log(f"[INPUT] jd chars={len(jd_text)} preview={preview(jd_text, 450)}")

        resume = get_resume_profile(resume_id)
        if not resume:
            payload = {
                "error": "Resume not found in Postgres for that s3_key.",
                "s3_key": s3_key,
                "resume_id": resume_id
            }
            return agent_response(event, payload) if is_agent else {"statusCode": 404, "body": json.dumps(payload)}

        jd_req = extract_jd_requirements(jd_text)
        result = score_resume(resume, jd_req)

        run_id = str(uuid.uuid4())
        try:
            with pg_conn() as conn, conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO resume_data.resume_match_runs(id, resume_id, jd_text, jd_requirements, result_json, overall_score)
                    VALUES (%s,%s,%s,%s::jsonb,%s::jsonb,%s)
                """, (run_id, resume_id, jd_text, json.dumps(jd_req), json.dumps(result), result["overall_score"]))
            log(f"[PG] ✅ saved match run id={run_id}")
        except Exception as e:
            log(f"[PG] ⚠️ could not save match run: {e}")

        payload = {"match_run_id": run_id, "jd_requirements": jd_req, "result": result}
        return agent_response(event, payload) if is_agent else {"statusCode": 200, "body": json.dumps(payload, indent=2)}

    except Exception as e:
        err = {"error": str(e), "traceback": traceback.format_exc()}
        log("[ERROR]\n" + json.dumps(err, indent=2))
        is_agent = ("messageVersion" in event and "function" in event)
        return agent_response(event, err) if is_agent else {"statusCode": 500, "body": json.dumps(err)}
