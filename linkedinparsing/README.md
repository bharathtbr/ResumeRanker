# LinkedIn Profile Parser Lambda

## Overview

This Lambda function processes LinkedIn profile PDFs uploaded to S3, validates they are genuine LinkedIn profiles, extracts skills and profile information, and automatically links them to existing resumes when possible.

## Key Features

✅ **LinkedIn Validation** - Uses Claude to verify PDF is a real LinkedIn profile  
✅ **Skill Extraction** - Extracts all skills including endorsement counts  
✅ **Auto-Mapping** - Automatically links LinkedIn profiles to resumes by name  
✅ **No Embeddings** - Simpler than resume parsing, no vector storage needed  
✅ **Separate Storage** - Uses different S3 buckets for resumes vs LinkedIn profiles  

---

## Architecture

```
LinkedIn PDF Upload (S3)
         ↓
    Lambda Triggered
         ↓
    ┌────────────────────┐
    │ 1. PDF Validation  │ → Is this a LinkedIn profile?
    └────────────────────┘
         ↓
    ┌────────────────────┐
    │ 2. Skill Extraction│ → Extract skills, certifications, etc.
    └────────────────────┘
         ↓
    ┌────────────────────┐
    │ 3. Store Profile   │ → Save to linkedin_profiles table
    └────────────────────┘
         ↓
    ┌────────────────────┐
    │ 4. Find Resume     │ → Match by name to existing resumes
    └────────────────────┘
         ↓
    ┌────────────────────┐
    │ 5. Create Mapping  │ → Link in linkedin_resume_mapping table
    └────────────────────┘
```

---

## Database Schema

### Table 1: `linkedin_profiles`

Stores LinkedIn profile data extracted from PDFs.

```sql
CREATE TABLE resume_data.linkedin_profiles (
    linkedin_id VARCHAR(40) PRIMARY KEY,  -- SHA1(s3_key)
    s3_key TEXT NOT NULL,
    file_name TEXT NOT NULL,
    s3_uri TEXT NOT NULL,
    
    -- Profile Info
    name TEXT,
    headline TEXT,
    location TEXT,
    profile_url TEXT,
    total_connections TEXT,
    
    -- Validation
    validation_confidence FLOAT,  -- 0.0-1.0
    validation_reason TEXT,
    
    -- Skills
    skills_json JSONB,
    skills_flat TEXT[],
    skills_hash VARCHAR(40),
    endorsement_counts JSONB,
    top_skills TEXT[],
    certifications TEXT[]
);
```

### Table 2: `linkedin_resume_mapping`

Many-to-many mapping between LinkedIn profiles and resumes.

```sql
CREATE TABLE resume_data.linkedin_resume_mapping (
    id UUID PRIMARY KEY,
    linkedin_id VARCHAR(40) REFERENCES linkedin_profiles,
    resume_id VARCHAR(40) REFERENCES resume_profiles,
    match_confidence FLOAT,
    match_method VARCHAR(50),  -- 'name_match', 'email_match', 'manual'
    CONSTRAINT unique_linkedin_resume UNIQUE (linkedin_id, resume_id)
);
```

---

## S3 Bucket Strategy

### Two Separate Buckets

**Bucket 1: Resumes** (`my-resumes-bucket`)
- Stores: `.pdf`, `.docx` resume files
- Triggers: `resumeparsing` Lambda
- Creates: Vector embeddings in S3 Vectors
- Stores: `resume_profiles`, `resume_chunks` tables

**Bucket 2: LinkedIn Profiles** (`my-linkedin-profiles-bucket`)
- Stores: `.pdf` LinkedIn profile exports
- Triggers: `linkedinparsing` Lambda (this one)
- No embeddings: Simple skill extraction only
- Stores: `linkedin_profiles` table

### Why Separate Buckets?

1. **Clear separation** of resume vs LinkedIn data
2. **Different triggers** for different Lambda functions
3. **Different processing** - resumes need chunking/embeddings, LinkedIn doesn't
4. **Security** - can have different access policies

---

## Mapping Strategy

### Automatic Mapping

The Lambda automatically tries to link LinkedIn → Resume using:

1. **Name Matching** (primary method)
   ```python
   SELECT resume_id FROM resume_profiles 
   WHERE LOWER(name) = LOWER('John Smith')
   ```

2. **Email Matching** (if available - rare in LinkedIn PDFs)
   ```python
   SELECT resume_id FROM resume_profiles 
   WHERE LOWER(email) = LOWER('john@example.com')
   ```

### Manual Mapping

If auto-mapping fails, you can manually create mappings:

```sql
-- Find unmatched LinkedIn profiles
SELECT * FROM resume_data.v_unmatched_linkedin_profiles;

-- Manually create mapping
INSERT INTO resume_data.linkedin_resume_mapping(id, linkedin_id, resume_id, match_confidence, match_method)
VALUES (gen_random_uuid(), 'linkedin_id_here', 'resume_id_here', 0.9, 'manual');
```

### One-to-Many Support

The mapping table supports:
- **Multiple resumes** for one LinkedIn profile (e.g., different versions)
- **Multiple LinkedIn profiles** for one resume (if someone has multiple accounts)

---

## Environment Variables

```bash
# Database
PG_DB=resumes
PG_USER=
PG_PASS=
PG_HOST=
PG_PORT=5432

# AWS
AWS_REGION=us-east-1
BEDROCK_LLM_MODEL=us.anthropic.claude-3-5-sonnet-20241022-v2:0

# S3 Buckets (for reference/logging)
RESUME_BUCKET=my-resumes-bucket
LINKEDIN_BUCKET=my-linkedin-profiles-bucket

# Logging
LOG_CLAUDE_CHARS=1600
```

---

## Deployment

### 1. Create Database Tables

```bash
psql -h  -U  -d resumes -f database_schema.sql
```

### 2. Create S3 Bucket

```bash
aws s3 mb s3://my-linkedin-profiles-bucket --region us-east-1
```

### 3. Create Lambda Function

```bash
# Create deployment package
pip install -r requirements.txt -t package/
cp lambda_function.py package/
cd package
zip -r ../linkedin-parser.zip .
cd ..

# Create Lambda
aws lambda create-function \
  --function-name linkedin-profile-parser \
  --runtime python3.11 \
  --role arn:aws:iam::YOUR_ACCOUNT:role/lambda-execution-role \
  --handler lambda_function.lambda_handler \
  --zip-file fileb://linkedin-parser.zip \
  --timeout 300 \
  --memory-size 512 \
  --environment Variables="{
    PG_DB=resumes,
    PG_USER=,
    PG_PASS=,
    PG_HOST=,
    PG_PORT=5432,
    RESUME_BUCKET=my-resumes-bucket,
    LINKEDIN_BUCKET=my-linkedin-profiles-bucket
  }"
```

### 4. Add S3 Trigger

```bash
aws s3api put-bucket-notification-configuration \
  --bucket my-linkedin-profiles-bucket \
  --notification-configuration '{
    "LambdaFunctionConfigurations": [{
      "LambdaFunctionArn": "arn:aws:lambda:us-east-1:ACCOUNT:function:linkedin-profile-parser",
      "Events": ["s3:ObjectCreated:*"],
      "Filter": {
        "Key": {"FilterRules": [{"Name": "suffix", "Value": ".pdf"}]}
      }
    }]
  }'
```

---

## Usage Examples

### Upload LinkedIn Profile

```bash
# Upload to LinkedIn bucket (triggers Lambda)
aws s3 cp john_smith_linkedin.pdf s3://my-linkedin-profiles-bucket/profiles/

# Lambda will:
# 1. Validate it's a LinkedIn PDF
# 2. Extract skills and profile data
# 3. Store in linkedin_profiles table
# 4. Try to find matching resume by name
# 5. Create mapping if found
```

### Query Combined Data

```sql
-- Get resume + LinkedIn data together
SELECT 
    resume_name,
    resume_skills,
    linkedin_name,
    linkedin_skills,
    linkedin_top_skills,
    match_confidence
FROM resume_data.v_linkedin_resume_combined
WHERE resume_id = 'xxx';
```

### Find Skill Overlaps

```sql
-- Compare resume skills vs LinkedIn skills
WITH overlaps AS (
    SELECT 
        resume_id,
        resume_skills,
        linkedin_skills,
        array(
            SELECT unnest(resume_skills) 
            INTERSECT 
            SELECT unnest(linkedin_skills)
        ) as common_skills
    FROM resume_data.v_linkedin_resume_combined
)
SELECT 
    resume_id,
    array_length(common_skills, 1) as overlap_count,
    array_length(resume_skills, 1) as resume_skill_count,
    array_length(linkedin_skills, 1) as linkedin_skill_count,
    common_skills
FROM overlaps
WHERE array_length(common_skills, 1) > 0;
```

---

## Expected Log Output

```
[INIT] region=us-east-1 resume_bucket=my-resumes-bucket linkedin_bucket=my-linkedin-profiles-bucket

[INGEST] file=s3://my-linkedin-profiles-bucket/profiles/john_smith.pdf
[INGEST] linkedin_id(sha1)=abc123...

[TEXT] chars=15234
[TEXT] preview:
John Smith
Senior Software Engineer | AWS | Docker | Kubernetes...

[CLAUDE] model=us.anthropic.claude-3-5-sonnet-20241022-v2:0 max_tokens=800
[VALIDATION] is_linkedin=True confidence=0.95 reason=Found LinkedIn branding, Skills section, and experience format
[VALIDATION] indicators=['linkedin.com', 'Skills & Endorsements', 'Experience', 'Education']

[CLAUDE] model=us.anthropic.claude-3-5-sonnet-20241022-v2:0 max_tokens=3000
[SKILLS] extracted from LinkedIn:
  name=John Smith headline=Senior Software Engineer
  location=San Francisco, CA profile_url=linkedin.com/in/johnsmith
  total_skills=42
  top_skills=['Docker', 'Kubernetes', 'AWS']
  certifications_count=3

[PG] upsert linkedin_profiles linkedin_id=abc123... file_name=john_smith.pdf

[MATCH] Found resume by name match: def456...
[MAPPING] Created linkedin_id=abc123... <-> resume_id=def456... (method=name_match)

[INGEST] ✅ done linkedin_id=abc123...
```

---

## Differences from Resume Parsing

| Feature | Resume Parsing | LinkedIn Parsing |
|---------|----------------|------------------|
| **Embeddings** | ✅ Yes (chunks vectorized) | ❌ No (simple extraction) |
| **Vector Storage** | ✅ S3 Vectors | ❌ Not needed |
| **Chunking** | ✅ 250-word chunks | ❌ Whole document |
| **Validation** | ❌ Assumes resume | ✅ Validates LinkedIn |
| **Mapping** | N/A | ✅ Auto-links to resumes |
| **Endorsements** | N/A | ✅ Captures counts |
| **Certifications** | Extracted in skills | ✅ Separate array |

---

## Troubleshooting

### Low Validation Confidence

If `validation_confidence < 0.5`, the PDF might not be a real LinkedIn export:

```sql
SELECT linkedin_id, name, validation_confidence, validation_reason
FROM resume_data.linkedin_profiles
WHERE validation_confidence < 0.5;
```

**Common causes:**
- Resume uploaded to LinkedIn bucket by mistake
- Non-standard LinkedIn export format
- Heavily redacted profile

### No Matching Resume Found

Check unmatched profiles:

```sql
SELECT * FROM resume_data.v_unmatched_linkedin_profiles;
```

**Solutions:**
1. Upload matching resume to resume bucket first
2. Manually create mapping (see "Manual Mapping" section)
3. Name might be formatted differently (e.g., "John A. Smith" vs "John Smith")

### Skills Not Extracted

```sql
SELECT linkedin_id, name, array_length(skills_flat, 1) as skill_count
FROM resume_data.linkedin_profiles
WHERE array_length(skills_flat, 1) < 5;
```

**Possible causes:**
- PDF text extraction issues
- Non-English profile
- Skills section not clearly labeled

---

## API for Manual Operations

### Create Manual Mapping

```python
import psycopg2

conn = psycopg2.connect(...)
cur = conn.cursor()

cur.execute("""
    INSERT INTO resume_data.linkedin_resume_mapping(id, linkedin_id, resume_id, match_confidence, match_method)
    VALUES (gen_random_uuid(), %s, %s, %s, 'manual')
    ON CONFLICT (linkedin_id, resume_id) DO NOTHING
""", (linkedin_id, resume_id, 1.0))

conn.commit()
```

### Update Validation

```python
cur.execute("""
    UPDATE resume_data.linkedin_profiles
    SET validation_confidence = %s, validation_reason = %s
    WHERE linkedin_id = %s
""", (0.9, "Manually verified", linkedin_id))
```

---

## Future Enhancements

- [ ] Support DOCX LinkedIn exports
- [ ] Fuzzy name matching (Levenshtein distance)
- [ ] Extract years of experience per skill
- [ ] Compare resume vs LinkedIn skill discrepancies
- [ ] Auto-detect profile URL changes
- [ ] Notification if skills diverge significantly
