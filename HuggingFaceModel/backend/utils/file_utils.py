import re

# Dummy skill extraction
def extract_skills(text):
    # Example: extract capitalized words as skills
    return list(set(re.findall(r'\b[A-Z][a-zA-Z]+\b', text)))

def semantic_missing_skills(resume_text, jd_skills, model, threshold=0.6):
    # Dummy: return skills not in resume_text
    missing = [s for s in jd_skills if s.lower() not in resume_text.lower()]
    return missing
