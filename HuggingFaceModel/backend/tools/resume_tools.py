from langchain.tools import BaseTool
from backend.vectorstore.resume_store import query_resumes
from backend.utils.file_utils import extract_skills
from backend.utils.scoring import compute_final_score
from backend.models.embed_model import embedding_for

class SearchResumeTool(BaseTool):
    name = "search_resume"
    description = "Search top matching resumes for a given JD using pgvector"

    def _run(self, query: str):
        jd_text = query.strip()
        if not jd_text:
            return "Query is empty."

        # Get embedding & skills
        jd_emb = embedding_for(jd_text)
        jd_skills = extract_skills(jd_text)

        # Query resumes from pgvector store
        results = query_resumes(jd_emb, top_k=20)

        hits = []
        for resume in results:
            resume_text = resume.text
            resume_skills_list = [s.strip() for s in (resume.skills or "").split(",") if s.strip()]
            distance = resume.embedding.cosine_distance(jd_emb)  # pgvector similarity
            score_dict = compute_final_score(jd_text, jd_skills, resume_text, resume_skills_list, distance)
