"""
Configuration file for Resume Scoring Lambda Function
"""

# Database Configuration
DB_CONFIG = {
    'host': 'your-rds-endpoint.rds.amazonaws.com',
    'database': 'resume_scoring_db',
    'user': 'admin',
    'password': 'your-secure-password',
    'port': 5432
}

# AWS Configuration
AWS_CONFIG = {
    'region': 'us-east-1',
    's3_bucket': 'your-resume-bucket',
    'bedrock_model_id': 'anthropic.claude-3-sonnet-20240229-v1:0'
}

# Scoring Weights (must sum to 1.0)
SCORING_WEIGHTS = {
    'skill_match': 0.40,
    'experience': 0.35,
    'education': 0.15,
    'additional': 0.10
}
