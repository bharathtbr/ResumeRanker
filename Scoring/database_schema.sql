-- Database schema for resume scoring

-- Job descriptions table  
CREATE TABLE IF NOT EXISTS job_descriptions (
    id SERIAL PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    company_name VARCHAR(255),
    location VARCHAR(255),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_jd_is_active ON job_descriptions(is_active);
CREATE INDEX idx_jd_title ON job_descriptions(title);

-- Resume scores table
CREATE TABLE IF NOT EXISTS resume_scores (
    id SERIAL PRIMARY KEY,
    s3_key VARCHAR(500) NOT NULL,
    jd_id INTEGER REFERENCES job_descriptions(id),
    jd_text TEXT,
    jd_requirements JSONB,
    overall_score INTEGER NOT NULL,
    scoring_details JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_rs_s3_key ON resume_scores(s3_key);
CREATE INDEX idx_rs_jd_id ON resume_scores(jd_id);
CREATE INDEX idx_rs_score ON resume_scores(overall_score DESC);
CREATE INDEX idx_rs_created ON resume_scores(created_at);
