"""
Multi-Metric Resume Scoring
Uses HuggingFace embeddings + skill experience data
"""

from backend.models.embeddings import get_embedding_model
import numpy as np
from typing import List, Dict

embed_model = get_embedding_model()

def calculate_skill_overlap(jd_skills: List[str], resume_skills: List[str]) -> Dict:
    """Calculate skill overlap"""
    jd_skills_lower = {s.lower() for s in jd_skills}
    resume_skills_lower = {s.lower() for s in resume_skills}
    
    matched = jd_skills_lower & resume_skills_lower
    missing = jd_skills_lower - resume_skills_lower
    
    overlap_ratio = len(matched) / len(jd_skills_lower) if jd_skills_lower else 0.0
    
    matched_skills = [s for s in jd_skills if s.lower() in matched]
    missing_skills = [s for s in jd_skills if s.lower() in missing]
    
    return {
        "overlap_ratio": overlap_ratio,
        "matched_skills": matched_skills,
        "missing_skills": missing_skills
    }

def calculate_experience_match(jd_years: int, resume_skill_exp: Dict, jd_skills: List[str]) -> Dict:
    """Calculate experience match from skill_experience_json"""
    if not resume_skill_exp or not jd_skills:
        return {"experience_ratio": 0.0, "skills_with_exp": {}}
    
    total_exp = 0.0
    skills_with_exp = {}
    
    for skill in jd_skills:
        skill_lower = skill.lower()
        
        for resume_skill, exp_data in resume_skill_exp.items():
            if resume_skill.lower() == skill_lower:
                total_years = exp_data.get("total_years", 0.0)
                total_exp += total_years
                skills_with_exp[skill] = {
                    "years": total_years,
                    "jobs_count": len(exp_data.get("jobs_using_skill", []))
                }
                break
    
    if jd_years > 0:
        experience_ratio = min(1.0, total_exp / (jd_years * len(jd_skills)))
    else:
        experience_ratio = 1.0 if total_exp > 0 else 0.0
    
    return {
        "experience_ratio": experience_ratio,
        "skills_with_exp": skills_with_exp,
        "total_exp": total_exp
    }

def compute_final_score(
    jd_text: str,
    jd_skills: List[str],
    jd_years: int,
    resume_text: str,
    resume_skills: List[str],
    resume_skill_exp: Dict,
    pgvector_similarity: float
) -> Dict:
    """
    Compute final score using:
    1. Embedding similarity (pgvector)
    2. Semantic similarity (HuggingFace on full texts)
    3. Skill overlap
    4. Experience match
    
    Final = 0.3*embedding + 0.3*semantic + 0.2*skill + 0.2*experience
    """
    
    # 1. Embedding similarity (from pgvector)
    embedding_score = pgvector_similarity
    
    # 2. Semantic similarity (HuggingFace)
    jd_emb = embed_model.encode(jd_text)
    resume_emb = embed_model.encode(resume_text)
    semantic_score = embed_model.similarity(jd_emb, resume_emb)
    
    # 3. Skill overlap
    skill_match = calculate_skill_overlap(jd_skills, resume_skills)
    skill_score = skill_match["overlap_ratio"]
    
    # 4. Experience match
    exp_match = calculate_experience_match(jd_years, resume_skill_exp, jd_skills)
    experience_score = exp_match["experience_ratio"]
    
    # Final weighted score
    final_score = (
        0.3 * embedding_score +
        0.3 * semantic_score +
        0.2 * skill_score +
        0.2 * experience_score
    )
    
    return {
        "score": round(final_score * 100, 2),  # 0-100 scale
        "embedding_similarity": round(embedding_score, 4),
        "semantic_similarity": round(semantic_score, 4),
        "skill_overlap": round(skill_score, 4),
        "experience_match": round(experience_score, 4),
        "matched_skills": skill_match["matched_skills"],
        "missing_skills": skill_match["missing_skills"],
        "skills_with_exp": exp_match["skills_with_exp"],
        "total_exp": round(exp_match["total_exp"], 1)
    }
