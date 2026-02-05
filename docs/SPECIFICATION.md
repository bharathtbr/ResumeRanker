# Resume Scoring System - Technical Specification Document

**Version:** 4.0
**Last Updated:** 2026-01-31
**Status:** Production

---

## 1. Executive Summary

The Resume Scoring System is an AI-powered enterprise solution designed to automatically parse, analyze, and score candidate resumes against job descriptions. The system leverages AWS cloud infrastructure, advanced LLM capabilities (Claude 3.5 Sonnet), and vector embeddings to provide accurate, explainable resume-to-job matching scores.

### Key Capabilities
- **Automated Resume Parsing:** Extract text, skills, work history, and experience from PDF/DOCX files
- **Intelligent Scoring:** Match resumes to job descriptions with 0-100 scoring and detailed breakdowns
- **Skill Experience Tracking:** Pre-calculate and track years of experience per skill across all jobs
- **LinkedIn Integration:** Parse and map LinkedIn profiles to resumes for enhanced candidate data
- **Vector Search:** Hybrid vector + lexical search for finding relevant resume evidence
- **Multi-Format Support:** Process resumes in PDF, DOCX, and TXT formats
- **Job Context Awareness:** Associate resume chunks with specific job roles for context-aware scoring

---

## 2. System Overview

### 2.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    RESUME INGESTION LAYER                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  S3 Upload → Lambda (Parse) → PostgreSQL + S3 Vectors            │
│  • Resume PDF/DOCX                                               │
│  • LinkedIn Profile PDF                                          │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                  PROCESSING & EXTRACTION LAYER                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  AWS Bedrock (Claude 3.5 Sonnet)                                │
│  • Skill Extraction                                              │
│  • Work History Extraction                                       │
│  • Skill Experience Calculation                                  │
│  • JD Requirements Extraction                                    │
│                                                                   │
│  Amazon Titan Embed Text v2                                      │
│  • Resume Chunk Embeddings (250 words)                           │
│  • JD Requirement Embeddings                                     │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    SCORING & MATCHING LAYER                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  Hybrid Vector Search (S3 Vectors)                               │
│  Claude Evidence Grading                                         │
│  Pre-Extracted Skill Experience Lookup                           │
│  Multi-Dimensional Score Aggregation                             │
│                                                                   │
│  Output: 0-100 Score + Detailed Breakdown                        │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 Core Components

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Resume Parsing Lambda** | Python 3.12, AWS Lambda | Extract text, skills, work history, and embeddings from resumes |
| **Resume Scoring Lambda** | Python 3.12, FastAPI, AWS Lambda | Score resumes against job descriptions |
| **LinkedIn Parser Lambda** | Python 3.12, AWS Lambda | Extract skills and metadata from LinkedIn PDFs |
| **Database** | PostgreSQL 14+ | Store resumes, chunks, work history, LinkedIn profiles, scores |
| **Vector Store** | AWS S3 Vectors | Store and search resume chunk embeddings |
| **LLM Service** | AWS Bedrock (Claude 3.5 Sonnet) | Extract information, grade evidence, calculate scores |
| **Embedding Service** | AWS Bedrock (Titan Embed Text v2) | Generate vector embeddings for semantic search |
| **File Storage** | AWS S3 | Store uploaded resume and LinkedIn PDF files |

### 2.3 Alternative Deployment: HuggingFace Backend

The system includes an alternative FastAPI-based backend that uses open-source models:
- **Embeddings:** HuggingFace SentenceTransformers
- **LLM:** Groq API
- **Framework:** LangChain agents for multi-step workflows
- **Deployment:** Standalone server (port 8000 - API, port 8001 - Agent)

---

## 3. Functional Requirements

### 3.1 Resume Parsing (FR-01)

**Description:** Extract structured information from uploaded resume files.

**Inputs:**
- S3 bucket name
- S3 object key (resume file path)
- Supported formats: PDF, DOCX, TXT

**Processing Steps:**
1. **Text Extraction**
   - PDF: Extract text page-by-page using PyPDF2
   - DOCX: Extract text using docx2txt
   - TXT: Direct UTF-8 decoding

2. **Skill Extraction** (Claude prompt)
   - Input: Full resume text
   - Output: JSON array of skills
   - Example: `["Python", "AWS", "PostgreSQL", "Docker", "Kubernetes"]`

3. **Work History Extraction** (Claude prompt)
   - Input: Full resume text
   - Output: Structured JSON with:
     - Company name
     - Job title
     - Start date (YYYY-MM format)
     - End date (YYYY-MM or "Present")
     - Duration in months
     - Description
     - Technologies used

4. **Skill Experience Calculation** (Claude prompt - NEW in v4)
   - For each major skill in the resume:
     - Find ALL jobs where the skill was used
     - Calculate total years of experience
     - Extract evidence/description for each job
   - Output format:
     ```json
     {
       "Python": {
         "total_years": 5.5,
         "jobs_breakdown": [
           {
             "company": "TechCorp Inc.",
             "duration_months": 24,
             "evidence": "Built backend APIs using Python Flask..."
           },
           {
             "company": "DataSoft LLC",
             "duration_months": 42,
             "evidence": "Developed ML pipelines in Python..."
           }
         ]
       }
     }
     ```

5. **Text Chunking**
   - Split resume into 250-word chunks with 50-word overlap
   - Preserve semantic boundaries (avoid mid-sentence breaks)
   - Associate each chunk with the closest job context

6. **Embedding Generation**
   - Create vector embeddings for each chunk using Amazon Titan Embed Text v2
   - Store embeddings in S3 Vectors for hybrid search

**Outputs:**
- `resume_profiles` table record:
  - `resume_id` (SHA1 hash of S3 key)
  - Full text
  - Skills JSON
  - **Skill experience JSON** (NEW)
  - Metadata (file name, upload date)

- `resume_chunks` table records:
  - Chunk text (250 words)
  - Vector key (S3 Vectors reference)
  - Job context JSONB (company, title, dates)
  - Page and chunk index

- `resume_work_history` table records:
  - One record per job
  - Structured work history data

**Performance Requirements:**
- Processing time: < 30 seconds for 5-page resume
- Accuracy: > 95% for skill extraction, > 90% for work history

---

### 3.2 Job Description Parsing (FR-02)

**Description:** Extract structured requirements from job descriptions.

**Inputs:**
- Job description ID (integer)
- Job description text (from database)

**Processing Steps:**
1. **Requirement Extraction** (Claude prompt)
   - Identify core skills (critical, required)
   - Identify secondary skills (required)
   - Identify nice-to-have skills (preferred)
   - Extract experience requirements (total years)
   - Extract keywords

2. **Skill Variant Generation**
   - For each skill, generate common variants
   - Examples:
     - ".NET" → ["dotnet", ".NET", "ASP.NET", "ASP.NET Core", ".NET 6", ".NET 7", ".NET 8", "C#"]
     - "AWS" → ["AWS", "Amazon Web Services", "EC2", "Lambda", "S3", "RDS"]
     - "PostgreSQL" → ["postgres", "postgresql", "RDS Postgres", "Aurora PostgreSQL"]

**Outputs:**
- Structured JD requirements JSON:
  ```json
  {
    "job_title": "Senior Backend Engineer",
    "core_skills": [
      {
        "name": "Python",
        "importance": "critical",
        "min_years": 5,
        "variants": ["python", "python3", "py"]
      }
    ],
    "secondary_skills": [...],
    "nice_to_have_skills": [...],
    "keywords": ["API", "microservices", "cloud"],
    "experience_requirements": {
      "total_years": 5
    }
  }
  ```

**Performance Requirements:**
- Processing time: < 10 seconds
- Accuracy: > 95% for core skill identification

---

### 3.3 Resume Scoring (FR-03)

**Description:** Score a resume against a job description with detailed breakdown.

**Inputs:**
- Resume ID (SHA1 hash)
- Job Description ID (integer)

**Processing Steps:**

#### Step 1: Vector Search for Each Skill
For each required skill in the JD:
1. Create embedding for skill query using Titan
2. Perform hybrid vector search in S3 Vectors:
   - Vector similarity (cosine distance)
   - Lexical matching (keyword presence)
3. Retrieve top matching chunk with job context

#### Step 2: Evidence Grading (Claude prompt)
For each matched chunk:
1. Send chunk + job context + skill to Claude
2. Claude evaluates:
   - Does chunk mention the skill?
   - How strong is the evidence (weak/moderate/strong)?
   - Does it show actual usage or just listing?
3. Output: `{"matched": true/false, "evidence_strength": "strong", "quote": "..."}`

#### Step 3: Skill Experience Lookup (NEW in v4)
For each skill:
1. Lookup pre-calculated `skill_experience_json` from `resume_profiles`
2. Retrieve `total_years` and `jobs_breakdown`
3. Compare against JD `min_years` requirement

#### Step 4: Score Calculation
For each skill:
```
skill_score = (evidence_strength * 0.6) + (years_match * 0.4)

evidence_strength:
  - strong: 1.0
  - moderate: 0.7
  - weak: 0.4
  - none: 0.0

years_match:
  - if resume_years >= required_years: 1.0
  - else: max(0, 1.0 - ((required_years - resume_years) * 0.15))
```

#### Step 5: Overall Score Aggregation
```
Core Skills Score (60% weight):
  matched_core / total_core * 100

Experience Score (25% weight):
  if resume_total_years >= jd_total_years: 100
  else: max(0, 100 - ((jd_total_years - resume_total_years) * 10))

Additional Factors (15% weight):
  +50 points if has certifications
  +50 points if has notable projects

Overall Score = (Core * 0.6) + (Experience * 0.25) + (Additional * 0.15)
```

**Outputs:**
- `resume_scores` table record:
  ```json
  {
    "overall_score": 85,
    "breakdown": {
      "core_skills_score": 90.0,
      "experience_score": 80.0,
      "additional_score": 75.0
    },
    "core_skill_matches": [
      {
        "skill": "Python",
        "matched": true,
        "evidence_strength": "strong",
        "years_found": 5.5,
        "years_required": 5,
        "meets_years_requirement": true,
        "projects_used_in": ["TechCorp Inc.", "DataSoft LLC"],
        "quote": "Built backend APIs using Python Flask..."
      }
    ],
    "matched_core_skills": 9,
    "total_core_skills": 10,
    "resume_years": 8.5,
    "required_years": 5
  }
  ```

**Performance Requirements:**
- Processing time: < 45 seconds for 10 core skills
- Accuracy: > 90% skill match detection

---

### 3.4 LinkedIn Profile Integration (FR-04)

**Description:** Parse LinkedIn profile PDFs and map to existing resumes.

**Inputs:**
- S3 bucket name
- S3 object key (LinkedIn PDF file)

**Processing Steps:**
1. **PDF Validation** (Claude prompt)
   - Check if PDF is actually a LinkedIn profile
   - Extract confidence score (0.0-1.0)
   - Provide validation reason

2. **Profile Extraction**
   - Name, headline, location
   - Profile URL, total connections
   - Skills with endorsement counts
   - Top skills (most endorsed)
   - Certifications

3. **Resume Mapping**
   - Auto-match by candidate name
   - Calculate match confidence
   - Record match method (name_match, email_match, manual)

**Outputs:**
- `linkedin_profiles` table record
- `linkedin_resume_mapping` table record (if match found)

**Performance Requirements:**
- Processing time: < 20 seconds
- Name matching accuracy: > 85%

---

## 4. Non-Functional Requirements

### 4.1 Performance (NFR-01)

| Metric | Requirement |
|--------|-------------|
| **Resume Parsing Latency** | < 30s for 5-page PDF |
| **JD Parsing Latency** | < 10s |
| **Scoring Latency** | < 45s for 10 core skills |
| **Vector Search Latency** | < 2s per skill query |
| **Concurrent Uploads** | Support 100 simultaneous resume uploads |
| **Database Query Time** | < 500ms for single resume retrieval |

### 4.2 Scalability (NFR-02)

- **Lambda Auto-Scaling:** Automatically scale to 1000 concurrent executions
- **Database Connections:** Support 100 concurrent PostgreSQL connections
- **Storage:** Support 1M+ resumes (50GB+ storage)
- **Vector Store:** Support 10M+ embeddings

### 4.3 Availability (NFR-03)

- **System Uptime:** 99.5% availability
- **Error Rate:** < 1% processing errors
- **Data Durability:** 99.999999999% (S3 standard)

### 4.4 Security (NFR-04)

- **Data Encryption:**
  - At rest: AES-256 (S3, RDS)
  - In transit: TLS 1.2+
- **Access Control:**
  - IAM roles for Lambda functions
  - Database user authentication (username/password)
  - S3 bucket policies (private by default)
- **PII Handling:**
  - Resume data contains PII (names, emails, phone numbers)
  - GDPR/CCPA compliance required
  - Data retention policy: 7 years

### 4.5 Observability (NFR-05)

- **Logging:**
  - CloudWatch Logs for Lambda execution
  - Structured JSON logs with request IDs
  - Log retention: 90 days
- **Monitoring:**
  - Lambda execution duration, memory usage
  - Database connection pool metrics
  - Error rates and retry attempts
- **Tracing:**
  - X-Ray tracing for distributed requests
  - Request ID correlation across services

---

## 5. Data Models

### 5.1 Database Schema

#### resume_profiles
```sql
CREATE TABLE resume_data.resume_profiles (
    resume_id VARCHAR(40) PRIMARY KEY,  -- SHA1(s3_key)
    s3_key TEXT NOT NULL UNIQUE,
    file_name TEXT,
    name TEXT,                          -- Candidate name
    text TEXT,                          -- Full resume text
    skills_json JSONB,                  -- ["Python", "AWS", ...]
    skill_experience_json JSONB,        -- NEW in v4
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

#### skill_experience_json Format
```json
{
  "Python": {
    "total_years": 5.5,
    "jobs_breakdown": [
      {
        "company": "TechCorp Inc.",
        "duration_months": 24,
        "evidence": "Built backend APIs..."
      }
    ]
  }
}
```

#### resume_chunks
```sql
CREATE TABLE resume_data.resume_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    resume_id VARCHAR(40) REFERENCES resume_data.resume_profiles(resume_id),
    vector_key VARCHAR(100) NOT NULL,   -- S3 Vectors key
    page INT,
    chunk_index INT,
    chunk_text TEXT,
    job_context JSONB,                  -- NEW: Associated job
    created_at TIMESTAMP DEFAULT NOW()
);
```

#### job_context JSONB Format
```json
{
  "company": "TechCorp Inc.",
  "title": "Senior Backend Engineer",
  "start_date": "2020-01",
  "end_date": "2022-01",
  "duration_months": 24
}
```

#### resume_work_history
```sql
CREATE TABLE resume_data.resume_work_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    resume_id VARCHAR(40) REFERENCES resume_data.resume_profiles(resume_id),
    company TEXT NOT NULL,
    title TEXT,
    start_date VARCHAR(10),             -- YYYY-MM
    end_date VARCHAR(10),               -- YYYY-MM or "Present"
    duration_months INT,
    description TEXT,
    technologies TEXT[],
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(resume_id, company, start_date)
);
```

#### linkedin_profiles
```sql
CREATE TABLE resume_data.linkedin_profiles (
    linkedin_id VARCHAR(40) PRIMARY KEY,
    s3_key TEXT NOT NULL,
    file_name TEXT,
    name TEXT,
    headline TEXT,
    location TEXT,
    profile_url TEXT,
    total_connections TEXT,
    validation_confidence FLOAT,
    validation_reason TEXT,
    skills_json JSONB,
    skills_flat TEXT[],
    endorsement_counts JSONB,
    top_skills TEXT[],
    certifications TEXT[],
    created_at TIMESTAMP DEFAULT NOW()
);
```

#### linkedin_resume_mapping
```sql
CREATE TABLE resume_data.linkedin_resume_mapping (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    linkedin_id VARCHAR(40) REFERENCES resume_data.linkedin_profiles(linkedin_id),
    resume_id VARCHAR(40) REFERENCES resume_data.resume_profiles(resume_id),
    match_confidence FLOAT,
    match_method VARCHAR(50),           -- 'name_match', 'email_match', 'manual'
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(linkedin_id, resume_id)
);
```

#### job_descriptions
```sql
CREATE TABLE resume_data.job_descriptions (
    id SERIAL PRIMARY KEY,
    title VARCHAR(255),
    description TEXT,
    company_name VARCHAR(255),
    location VARCHAR(255),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

#### resume_scores
```sql
CREATE TABLE resume_data.resume_scores (
    id SERIAL PRIMARY KEY,
    s3_key VARCHAR(500),
    jd_id INT REFERENCES resume_data.job_descriptions(id),
    jd_text TEXT,
    jd_requirements JSONB,
    overall_score INT,
    scoring_details JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### 5.2 S3 Vectors Schema

#### Resume Chunk Embeddings
- **Index Name:** `resume-chunks-index`
- **Vector Dimension:** 1024 (Titan Embed Text v2)
- **Metadata:**
  ```json
  {
    "resume_id": "abc123...",
    "chunk_id": "uuid-1234...",
    "page": 1,
    "chunk_index": 0,
    "company": "TechCorp Inc.",
    "title": "Senior Engineer"
  }
  ```

---

## 6. API Specifications

### 6.1 Resume Parsing Lambda

**Function Name:** `resume-parser-v2`
**Runtime:** Python 3.12
**Memory:** 1024 MB
**Timeout:** 300 seconds

#### Invocation Methods

**Method 1: S3 Trigger (Automatic)**
```json
{
  "Records": [
    {
      "s3": {
        "bucket": {"name": "resume-uploads-bucket"},
        "object": {"key": "uploads/john_doe_resume.pdf"}
      }
    }
  ]
}
```

**Method 2: Direct Invocation**
```json
{
  "s3_bucket": "resume-uploads-bucket",
  "s3_key": "uploads/john_doe_resume.pdf"
}
```

#### Response Format
```json
{
  "statusCode": 200,
  "body": {
    "success": true,
    "resume_id": "a3f4b2c1d5e6...",
    "s3_key": "uploads/john_doe_resume.pdf",
    "file_name": "john_doe_resume.pdf",
    "name": "John Doe",
    "skills_count": 25,
    "total_experience_years": 8.5,
    "jobs_extracted": 4,
    "chunks_created": 12,
    "skill_experience_calculated": true,
    "timestamp": "2026-01-31T10:30:00Z"
  }
}
```

### 6.2 Resume Scoring Lambda

**Function Name:** `resume-scorer-v4`
**Runtime:** Python 3.12
**Memory:** 2048 MB
**Timeout:** 300 seconds

#### Request Format
```json
{
  "resume_id": "a3f4b2c1d5e6...",
  "jd_id": 42
}
```

#### Response Format
```json
{
  "statusCode": 200,
  "body": {
    "success": true,
    "overall_score": 85,
    "breakdown": {
      "core_skills_score": 90.0,
      "experience_score": 80.0,
      "additional_score": 75.0
    },
    "core_skill_matches": [
      {
        "skill": "Python",
        "matched": true,
        "evidence_strength": "strong",
        "years_found": 5.5,
        "years_required": 5,
        "meets_years_requirement": true,
        "projects_used_in": ["TechCorp Inc.", "DataSoft LLC"],
        "quote": "Built backend APIs using Python Flask and PostgreSQL, handling 10M+ requests/day"
      }
    ],
    "matched_core_skills": 9,
    "total_core_skills": 10,
    "resume_years": 8.5,
    "required_years": 5,
    "timestamp": "2026-01-31T10:35:00Z"
  }
}
```

### 6.3 LinkedIn Parser Lambda

**Function Name:** `linkedin-parser`
**Runtime:** Python 3.12
**Memory:** 1024 MB
**Timeout:** 180 seconds

#### Request Format
```json
{
  "s3_bucket": "linkedin-uploads-bucket",
  "s3_key": "profiles/john_doe_linkedin.pdf"
}
```

#### Response Format
```json
{
  "statusCode": 200,
  "body": {
    "success": true,
    "linkedin_id": "xyz789...",
    "name": "John Doe",
    "validation_confidence": 0.95,
    "skills_count": 30,
    "top_skills": ["Python", "AWS", "PostgreSQL"],
    "resume_mapped": true,
    "matched_resume_id": "a3f4b2c1d5e6...",
    "match_confidence": 0.88,
    "timestamp": "2026-01-31T10:40:00Z"
  }
}
```

---

## 7. Integration Points

### 7.1 AWS Bedrock

**Service:** AWS Bedrock Runtime
**Region:** us-east-1

#### Claude 3.5 Sonnet (LLM)
- **Model ID:** `us.anthropic.claude-3-5-sonnet-20241022-v2:0`
- **Use Cases:**
  - Skill extraction
  - Work history extraction
  - Skill experience calculation
  - JD requirement extraction
  - Evidence grading
- **API Call Example:**
  ```python
  response = bedrock_runtime.invoke_model(
      modelId='us.anthropic.claude-3-5-sonnet-20241022-v2:0',
      body=json.dumps({
          "anthropic_version": "bedrock-2023-05-31",
          "max_tokens": 2000,
          "messages": [{"role": "user", "content": prompt}],
          "temperature": 0.0
      })
  )
  ```

#### Amazon Titan Embed Text v2 (Embeddings)
- **Model ID:** `amazon.titan-embed-text-v2:0`
- **Vector Dimension:** 1024
- **Use Cases:**
  - Resume chunk embeddings
  - JD requirement embeddings
  - Semantic search queries

### 7.2 AWS S3

**Bucket Structure:**
```
resume-uploads-bucket/
  uploads/
    john_doe_resume.pdf
    jane_smith_resume.docx

linkedin-uploads-bucket/
  profiles/
    john_doe_linkedin.pdf
```

### 7.3 AWS S3 Vectors

**Index Configuration:**
- **Engine:** Amazon OpenSearch Serverless (vector engine)
- **Dimension:** 1024
- **Distance Metric:** Cosine similarity
- **Hybrid Search:** Enabled (vector + lexical)

### 7.4 PostgreSQL Database

**Connection Details:**
- **Host:** ********
- **Port:** 5432
- **Database:** resumes
- **Schema:** resume_data
- **User:** 
- **Password:******* (to be rotated to AWS Secrets Manager)

---

## 8. Error Handling

### 8.1 Error Codes

| Code | Description | Recovery Action |
|------|-------------|-----------------|
| **ERR_S3_READ** | Cannot read file from S3 | Verify bucket/key exists, check IAM permissions |
| **ERR_PDF_EXTRACT** | PDF extraction failed | Check if PDF is corrupted, try alternative parser |
| **ERR_BEDROCK_INVOKE** | Bedrock API call failed | Retry with exponential backoff, check quotas |
| **ERR_DB_CONNECT** | Database connection failed | Check network, verify credentials |
| **ERR_DB_INSERT** | Database insert failed | Check schema, verify constraints |
| **ERR_JSON_PARSE** | Claude returned invalid JSON | Re-prompt with stricter instructions |
| **ERR_VECTOR_SEARCH** | Vector search failed | Check S3 Vectors availability |

### 8.2 Retry Strategy

- **Transient Errors:** Retry up to 3 times with exponential backoff (1s, 2s, 4s)
- **Bedrock Throttling:** Retry up to 5 times with jitter
- **Database Deadlocks:** Retry up to 3 times immediately

### 8.3 Logging Format

```json
{
  "timestamp": "2026-01-31T10:30:00Z",
  "level": "ERROR",
  "request_id": "abc-123-def",
  "resume_id": "xyz789",
  "error_code": "ERR_BEDROCK_INVOKE",
  "error_message": "ThrottlingException: Rate exceeded",
  "retry_count": 2,
  "stack_trace": "..."
}
```

---

## 9. Deployment Specifications

### 9.1 Lambda Configuration

#### Resume Parser Lambda
```yaml
FunctionName: resume-parser-v2
Runtime: python3.12
Handler: lambda_function.lambda_handler
MemorySize: 1024
Timeout: 300
Environment:
  AWS_REGION: us-east-1
  PG_DB: resumes
  PG_USER: 
  PG_PASS: ********
  PG_HOST: ********
  PG_PORT: 5432
  VECTOR_BUCKET: resume-vectors-bucket
  VECTOR_INDEX: resume-chunks-index
  BEDROCK_EMBED_MODEL: amazon.titan-embed-text-v2:0
  BEDROCK_LLM_MODEL: us.anthropic.claude-3-5-sonnet-20241022-v2:0
  DEBUG: "false"
Layers:
  - arn:aws:lambda:us-east-1:123456789012:layer:psycopg2:1
  - arn:aws:lambda:us-east-1:123456789012:layer:PyPDF2:1
```

#### Resume Scorer Lambda
```yaml
FunctionName: resume-scorer-v4
Runtime: python3.12
Handler: lambda_handler.handler
MemorySize: 2048
Timeout: 300
Environment:
  # Same as parser +
  LOG_CLAUDE_CHARS: "1600"
  LOG_CHUNK_CHARS: "400"
```

### 9.2 IAM Policies

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject"
      ],
      "Resource": [
        "arn:aws:s3:::resume-uploads-bucket/*",
        "arn:aws:s3:::linkedin-uploads-bucket/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel"
      ],
      "Resource": [
        "arn:aws:bedrock:us-east-1::foundation-model/us.anthropic.claude-3-5-sonnet-20241022-v2:0",
        "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v2:0"
      ]
    },
    {
      "Effect": "Allow",
      "Action": [
        "aoss:APIAccessAll"
      ],
      "Resource": "arn:aws:aoss:us-east-1:123456789012:collection/*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "arn:aws:logs:us-east-1:123456789012:*"
    }
  ]
}
```

---

## 10. Testing Requirements

### 10.1 Unit Tests

- **Resume Parsing:**
  - Test PDF extraction (5-page, 10-page, corrupted PDF)
  - Test DOCX extraction
  - Test skill extraction accuracy (against labeled dataset)
  - Test work history extraction accuracy
  - Test skill experience calculation logic

- **Resume Scoring:**
  - Test vector search (precision@5, recall@5)
  - Test evidence grading (against human labels)
  - Test score calculation (verify math)
  - Test edge cases (no skills matched, all skills matched)

### 10.2 Integration Tests

- **End-to-End Flow:**
  1. Upload resume → Parse → Verify database records
  2. Create JD → Extract requirements → Verify structure
  3. Score resume → Verify score range and breakdown
  4. Upload LinkedIn → Map to resume → Verify mapping

### 10.3 Performance Tests

- **Load Test:**
  - 100 concurrent resume uploads
  - Measure: P50, P95, P99 latency
  - Verify: No Lambda throttling, no database connection exhaustion

- **Stress Test:**
  - 500 concurrent requests
  - Measure: Error rate, timeout rate
  - Verify: Graceful degradation

---

## 11. Maintenance & Operations

### 11.1 Monitoring Dashboards

**CloudWatch Dashboard Widgets:**
1. Lambda invocation count (parser, scorer, LinkedIn parser)
2. Lambda error rate (%)
3. Lambda duration (P50, P95, P99)
4. Database connection pool usage
5. Bedrock API call count and errors
6. S3 Vectors search latency

### 11.2 Alerts

| Alert | Condition | Severity | Action |
|-------|-----------|----------|--------|
| High Error Rate | > 5% errors in 5 minutes | Critical | Page on-call engineer |
| Lambda Timeout | > 10 timeouts in 10 minutes | High | Investigate slow queries |
| Database Connection Exhaustion | > 90% connections used | High | Scale RDS or reduce pool size |
| Bedrock Throttling | > 100 throttles in 5 minutes | Medium | Request quota increase |

### 11.3 Backup & Recovery

- **Database Backups:**
  - Automated daily snapshots (7-day retention)
  - Manual snapshot before schema changes
  - Point-in-time recovery enabled

- **S3 Backups:**
  - Versioning enabled
  - Lifecycle policy: Transition to Glacier after 90 days

---

## 12. Future Enhancements

### 12.1 Planned Features (Q2 2026)

1. **Multi-Language Support:**
   - Parse resumes in Spanish, French, German
   - Use Claude's multilingual capabilities

2. **Resume Redaction:**
   - Auto-remove PII (names, addresses, phone numbers)
   - Anonymized scoring for bias reduction

3. **Candidate Ranking API:**
   - Rank all resumes for a JD
   - Return top N candidates with scores

4. **Real-Time WebSocket Scoring:**
   - Stream scoring progress to frontend
   - Show per-skill results as they complete

### 12.2 Research Items

1. **Fine-Tuned Skill Extraction Model:**
   - Train custom model on 10K labeled resumes
   - Reduce Bedrock costs by 80%

2. **Graph-Based Skill Relationships:**
   - Build knowledge graph of skill relationships
   - Improve scoring for related skills (e.g., React → JavaScript)

3. **Experience Quality Scoring:**
   - Distinguish between "used Python" vs. "architected Python microservices"
   - Weight senior-level experience higher

---

## 13. Glossary

| Term | Definition |
|------|------------|
| **Resume Chunk** | 250-word segment of resume text with 50-word overlap |
| **Skill Experience** | Pre-calculated breakdown of years per skill across all jobs |
| **Job Context** | Company, title, dates associated with a resume chunk |
| **Evidence Grading** | Claude's assessment of how well a chunk demonstrates a skill |
| **Hybrid Search** | Vector similarity + lexical keyword matching |
| **Core Skills** | Critical/required skills from JD (60% weight in scoring) |
| **Secondary Skills** | Required but not critical skills from JD |
| **Nice-to-Have Skills** | Preferred skills from JD (bonus points) |

---

## 14. References

- **AWS Bedrock Documentation:** https://docs.aws.amazon.com/bedrock/
- **Claude API Reference:** https://docs.anthropic.com/claude/reference
- **PostgreSQL Documentation:** https://www.postgresql.org/docs/
- **S3 Vectors Guide:** https://aws.amazon.com/s3/features/vector-search/

---

**Document Control:**
- **Version History:**
  - v1.0 (2025-01-15): Initial specification
  - v2.0 (2025-02-10): Added job context feature
  - v3.0 (2025-03-05): Added LinkedIn integration
  - v4.0 (2026-01-31): Added skill experience pre-calculation
- **Approved By:** Engineering Lead
- **Next Review Date:** 2026-04-30
