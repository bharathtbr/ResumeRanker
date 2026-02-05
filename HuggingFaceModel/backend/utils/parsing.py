"""
Resume Parsing Utilities - Using Groq (No AWS Bedrock)
Uses Groq LLM for skill extraction instead of AWS Claude
"""

import os, io, json, tempfile, traceback, hashlib, re, uuid
from typing import Dict, List
import docx2txt
from PyPDF2 import PdfReader
from groq import Groq

# Groq Configuration
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
groq_client = Groq(api_key=GROQ_API_KEY)

# =========================
# Utility Functions
# =========================
def sha1_hex(s: str) -> str:
    return hashlib.sha1((s or "").encode("utf-8")).hexdigest()

def canonical_resume_id(filename: str) -> str:
    return sha1_hex(filename)

def clean_json_response(text: str) -> str:
    """Remove JSON wrappers"""
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

def invoke_groq(prompt: str, max_tokens: int = 2500) -> str:
    """Call Groq LLM instead of AWS Claude"""
    print(f"[GROQ] Calling llama-3.3-70b-versatile, max_tokens={max_tokens}")
    
    try:
        chat_completion = groq_client.chat.completions.create(
            messages=[
                {"role": "user", "content": prompt}
            ],
            model="llama-3.3-70b-versatile",
            temperature=0.0,
            max_tokens=max_tokens
        )
        
        text = chat_completion.choices[0].message.content.strip()
        text = clean_json_response(text)
        return text
        
    except Exception as e:
        print(f"[GROQ] Error: {e}")
        raise

def find_linkedin(full_text: str) -> str:
    """Extract LinkedIn URL"""
    if not full_text:
        return ""
    m = re.search(r"(https?://(www\.)?linkedin\.com/[^\s)>,]+)", full_text, flags=re.I)
    if m:
        return m.group(1).strip()
    m2 = re.search(r"((www\.)?linkedin\.com/[^\s)>,]+)", full_text, flags=re.I)
    if m2:
        v = m2.group(1).strip()
        return v if v.lower().startswith("http") else ("https://" + v)
    return ""

# =========================
# File Extraction
# =========================
def extract_docx_text(file_bytes: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        tmp.write(file_bytes)
        tmp.flush()
        path = tmp.name
    try:
        return docx2txt.process(path) or ""
    finally:
        try:
            os.unlink(path)
        except:
            pass

def extract_pdf_text(file_bytes: bytes) -> str:
    """Extract text from PDF"""
    pages = []
    with io.BytesIO(file_bytes) as pdf_stream:
        reader = PdfReader(pdf_stream)
        for i, p in enumerate(reader.pages):
            text = p.extract_text() or ""
            if text:
                pages.append(text)
    return "\n".join(pages)

def extract_text_from_file(file_path: str) -> str:
    """Extract text from PDF or DOCX file"""
    with open(file_path, 'rb') as f:
        file_bytes = f.read()
    
    if file_path.lower().endswith(".pdf"):
        return extract_pdf_text(file_bytes)
    elif file_path.lower().endswith(".docx"):
        return extract_docx_text(file_bytes)
    else:
        raise ValueError("Unsupported file format. Use PDF or DOCX.")

# =========================
# Chunking
# =========================
def chunk_text(text, chunk_words=250, overlap=50):
    """Split text into overlapping chunks"""
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

# =========================
# Skill Extraction (Using Groq)
# =========================
def extract_full_skills(full_text: str, resume_id: str) -> dict:
    """Extract skills using Groq LLM (not AWS)"""
    full_text = (full_text or "")[:25000]
    
    prompt = f"""You are an expert ATS resume parser.

Extract ALL skills mentioned ANYWHERE (skills section + bullets + responsibilities + projects).
Also extract name/email/phone/location/title/years_exp and LinkedIn if present.

Return ONLY valid JSON (no markdown, no explanation).

Resume:
{full_text}

Return this exact JSON structure:
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
- Deduplicate case-insensitive
- Use canonical names (".NET 6", "ASP.NET Core", "PostgreSQL")
- Extract ALL technical skills from entire resume
"""
    
    raw = invoke_groq(prompt)
    data = json.loads(raw)
    
    if not data.get("linkedin_url"):
        data["linkedin_url"] = find_linkedin(full_text)
    
    if not data.get("skills_flat_unique"):
        flat = []
        for _, arr in (data.get("skills") or {}).items():
            if isinstance(arr, list):
                flat.extend(arr)
        seen, uniq = set(), []
        for x in flat:
            x = str(x).strip()
            k = x.lower()
            if x and k not in seen:
                seen.add(k)
                uniq.append(x)
        data["skills_flat_unique"] = uniq
    
    print(f"[SKILLS] extracted {len(data.get('skills_flat_unique', []))} skills")
    return data

# =========================
# Skill Experience Extraction (Using Groq)
# =========================
def extract_skill_experience_breakdown(full_text: str, skills_list: list) -> dict:
    """Extract experience breakdown for each skill using Groq"""
    
    if not skills_list:
        print("[SKILL_EXP] No skills to extract")
        return {}
    
    full_text_for_analysis = full_text[:100000]
    
    print(f"[SKILL_EXP] Full text: {len(full_text)} chars")
    print(f"[SKILL_EXP] Analyzing: {len(full_text_for_analysis)} chars")
    
    # Process in batches
    all_results = {}
    batch_size = 10
    
    for i in range(0, len(skills_list), batch_size):
        batch_skills = skills_list[i:i+batch_size]
        skills_str = ", ".join(batch_skills)
        
        print(f"[SKILL_EXP] Batch {i//batch_size + 1}: {len(batch_skills)} skills")
        
        prompt = f"""Extract work experience for these skills from the resume.

Skills to analyze: {skills_str}

Resume:
{full_text_for_analysis}

Return ONE JSON object with ALL skills:
{{
  "skill1": {{"jobs_using_skill": [{{"company": "X", "start_date": "YYYY-MM", "end_date": "YYYY-MM", "duration_months": N, "evidence": "..."}}]}},
  "skill2": {{"jobs_using_skill": [...]}}
}}

Variants (treat as same skill):
- AWS EC2 = Amazon EC2 = EC2
- .NET = dotnet = ASP.NET = C# = .NET 6

Rules:
- Return ONE JSON object with ALL skills
- Only include skills actually USED in work experience
- Scan ENTIRE work history in resume
- Calculate duration_months accurately
- If skill not used in work: {{"jobs_using_skill": []}}
- No markdown, no explanation, just JSON
"""
        
        try:
            raw = invoke_groq(prompt, max_tokens=4000)
            
            # Clean
            raw = raw.strip()
            start = raw.find('{')
            end = raw.rfind('}')
            
            if start == -1 or end == -1:
                continue
            
            raw = raw[start:end+1]
            
            if '}{' in raw:
                raw = raw[:raw.find('}{') + 1]
            
            batch_data = json.loads(raw)
            
            # Merge with existing
            for skill, skill_data in batch_data.items():
                if skill in all_results:
                    existing_jobs = all_results[skill].get("jobs_using_skill", [])
                    new_jobs = skill_data.get("jobs_using_skill", [])
                    
                    all_jobs = existing_jobs + new_jobs
                    seen_companies = set()
                    merged_jobs = []
                    
                    for job in all_jobs:
                        company = job.get("company", "")
                        if company and company not in seen_companies:
                            seen_companies.add(company)
                            merged_jobs.append(job)
                    
                    all_results[skill]["jobs_using_skill"] = merged_jobs
                else:
                    all_results[skill] = skill_data
            
        except Exception as e:
            print(f"[SKILL_EXP] Batch error: {e}")
            continue
    
    # Calculate total_years
    for skill, skill_data in all_results.items():
        if isinstance(skill_data, dict) and "jobs_using_skill" in skill_data:
            jobs = skill_data["jobs_using_skill"]
            
            if not jobs:
                skill_data["total_years"] = 0.0
                continue
            
            total_months = 0
            for j in jobs:
                months = j.get("duration_months")
                if months is not None:
                    total_months += int(months)
            
            skill_data["total_years"] = round(total_months / 12.0, 1)
            
            print(f"[SKILL_EXP] {skill}: {skill_data['total_years']}y across {len(jobs)} jobs")
    
    print(f"[SKILL_EXP] ✅ Total: {len(all_results)} skills")
    return all_results

# =========================
# Main Parse Function
# =========================
def parse_resume(file_path: str, filename: str = None) -> dict:
    """
    Main parsing function using Groq (not AWS)
    
    Returns:
        {
            "resume_id": str,
            "filename": str,
            "full_text": str,
            "chunks": list,
            "skills_data": dict,
            "skill_experience": dict
        }
    """
    
    if filename is None:
        filename = os.path.basename(file_path)
    
    print(f"\n[PARSE] Starting: {filename}")
    
    # Extract text
    full_text = extract_text_from_file(file_path)
    print(f"[TEXT] Extracted {len(full_text)} chars")
    
    if not full_text.strip():
        raise ValueError("Empty text extracted")
    
    # Generate resume ID
    resume_id = canonical_resume_id(filename)
    print(f"[RESUME_ID] {resume_id}")
    
    # Extract skills using Groq
    skills_data = extract_full_skills(full_text, resume_id)
    
    # Extract skill experience using Groq
    skills_list = skills_data.get("skills_flat_unique", [])
    skill_experience = extract_skill_experience_breakdown(full_text, skills_list)
    
    # Create chunks
    chunks = chunk_text(full_text)
    print(f"[CHUNKS] Created {len(chunks)} chunks")
    
    return {
        "resume_id": resume_id,
        "filename": filename,
        "full_text": full_text,
        "chunks": chunks,
        "skills_data": skills_data,
        "skill_experience": skill_experience
    }


# Example usage
if __name__ == "__main__":
    result = parse_resume("../uploads/test_resume.pdf")
    print(json.dumps(result, indent=2, default=str))
