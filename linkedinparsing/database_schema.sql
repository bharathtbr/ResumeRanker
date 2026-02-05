-- =========================
-- LinkedIn Profile Tables
-- =========================

-- Table 1: LinkedIn Profiles (main table)
CREATE TABLE IF NOT EXISTS resume_data.linkedin_profiles (
    linkedin_id VARCHAR(40) PRIMARY KEY,  -- SHA1 hash of S3 key
    s3_key TEXT NOT NULL,
    file_name TEXT NOT NULL,
    s3_uri TEXT NOT NULL,
    
    -- Profile Information
    name TEXT,
    headline TEXT,
    location TEXT,
    profile_url TEXT,
    total_connections TEXT,
    
    -- Validation
    validation_confidence FLOAT DEFAULT 0.0,
    validation_reason TEXT,
    
    -- Skills Data
    skills_json JSONB NOT NULL,  -- Full structured skills
    skills_flat TEXT[],           -- Flat array of all skills
    skills_hash VARCHAR(40),      -- Hash for quick comparison
    
    -- LinkedIn Specific
    endorsement_counts JSONB,    -- {"Docker": 25, "AWS": 18, ...}
    top_skills TEXT[],           -- Most endorsed skills
    certifications TEXT[],       -- Certifications mentioned
    
    -- Metadata
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);

-- Indexes for linkedin_profiles
CREATE INDEX IF NOT EXISTS idx_linkedin_profiles_name 
    ON resume_data.linkedin_profiles(LOWER(name));
CREATE INDEX IF NOT EXISTS idx_linkedin_profiles_s3_key 
    ON resume_data.linkedin_profiles(s3_key);
CREATE INDEX IF NOT EXISTS idx_linkedin_profiles_validation 
    ON resume_data.linkedin_profiles(validation_confidence);
CREATE INDEX IF NOT EXISTS idx_linkedin_profiles_skills_hash 
    ON resume_data.linkedin_profiles(skills_hash);

-- GIN index for skills search
CREATE INDEX IF NOT EXISTS idx_linkedin_profiles_skills_gin 
    ON resume_data.linkedin_profiles USING GIN(skills_flat);

-- Table 2: LinkedIn-Resume Mapping (many-to-many)
CREATE TABLE IF NOT EXISTS resume_data.linkedin_resume_mapping (
    id UUID PRIMARY KEY,
    linkedin_id VARCHAR(40) NOT NULL REFERENCES resume_data.linkedin_profiles(linkedin_id) ON DELETE CASCADE,
    resume_id VARCHAR(40) NOT NULL REFERENCES resume_data.resume_profiles(resume_id) ON DELETE CASCADE,
    
    -- Matching Metadata
    match_confidence FLOAT DEFAULT 0.5,  -- How confident we are in this mapping
    match_method VARCHAR(50),  -- 'name_match', 'email_match', 'manual', etc.
    
    -- Metadata
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now(),
    
    CONSTRAINT unique_linkedin_resume UNIQUE (linkedin_id, resume_id)
);

-- Indexes for mapping table
CREATE INDEX IF NOT EXISTS idx_linkedin_resume_mapping_linkedin 
    ON resume_data.linkedin_resume_mapping(linkedin_id);
CREATE INDEX IF NOT EXISTS idx_linkedin_resume_mapping_resume 
    ON resume_data.linkedin_resume_mapping(resume_id);
CREATE INDEX IF NOT EXISTS idx_linkedin_resume_mapping_confidence 
    ON resume_data.linkedin_resume_mapping(match_confidence);

-- =========================
-- Helpful Views
-- =========================

-- View: Linked profiles with resume data
CREATE OR REPLACE VIEW resume_data.v_linkedin_resume_combined AS
SELECT 
    lp.linkedin_id,
    lp.name as linkedin_name,
    lp.headline,
    lp.location as linkedin_location,
    lp.total_connections,
    lp.validation_confidence,
    lp.skills_flat as linkedin_skills,
    lp.top_skills as linkedin_top_skills,
    lp.certifications,
    
    lrm.match_confidence,
    lrm.match_method,
    
    rp.resume_id,
    rp.name as resume_name,
    rp.email,
    rp.phone,
    rp.title,
    rp.years_exp,
    rp.skills_flat as resume_skills,
    rp.s3_key as resume_s3_key,
    
    lp.created_at as linkedin_created_at,
    rp.created_at as resume_created_at
FROM resume_data.linkedin_profiles lp
LEFT JOIN resume_data.linkedin_resume_mapping lrm ON lp.linkedin_id = lrm.linkedin_id
LEFT JOIN resume_data.resume_profiles rp ON lrm.resume_id = rp.resume_id;

-- View: Unmatched LinkedIn profiles (need manual review)
CREATE OR REPLACE VIEW resume_data.v_unmatched_linkedin_profiles AS
SELECT 
    lp.linkedin_id,
    lp.name,
    lp.headline,
    lp.location,
    lp.validation_confidence,
    lp.file_name,
    lp.created_at,
    array_length(lp.skills_flat, 1) as skills_count
FROM resume_data.linkedin_profiles lp
LEFT JOIN resume_data.linkedin_resume_mapping lrm ON lp.linkedin_id = lrm.linkedin_id
WHERE lrm.linkedin_id IS NULL
ORDER BY lp.created_at DESC;

-- =========================
-- Useful Queries
-- =========================

-- Find LinkedIn profiles with high validation confidence
-- SELECT * FROM resume_data.linkedin_profiles 
-- WHERE validation_confidence >= 0.8
-- ORDER BY created_at DESC;

-- Find all skills from a LinkedIn profile
-- SELECT skills_flat FROM resume_data.linkedin_profiles 
-- WHERE linkedin_id = 'xxx';

-- Find LinkedIn profiles with specific skill
-- SELECT linkedin_id, name, headline 
-- FROM resume_data.linkedin_profiles 
-- WHERE 'Docker' = ANY(skills_flat);

-- Get combined resume + LinkedIn data
-- SELECT * FROM resume_data.v_linkedin_resume_combined
-- WHERE resume_id = 'xxx';

-- Find potential matches (same name, not yet mapped)
-- SELECT lp.linkedin_id, lp.name, rp.resume_id, rp.name
-- FROM resume_data.linkedin_profiles lp
-- CROSS JOIN resume_data.resume_profiles rp
-- WHERE LOWER(lp.name) = LOWER(rp.name)
-- AND NOT EXISTS (
--     SELECT 1 FROM resume_data.linkedin_resume_mapping lrm 
--     WHERE lrm.linkedin_id = lp.linkedin_id 
--     AND lrm.resume_id = rp.resume_id
-- );
