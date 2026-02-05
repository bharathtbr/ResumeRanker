from langchain.tools import BaseTool
from backend.vectorstore.jobs_store import add_job
from backend.utils.file_utils import extract_skills
from backend.models.embed_model import embedding_for
from uuid import uuid4

class AddJDTool(BaseTool):
    name = "add_jd"
    description = "Add a Job Description (JD) into the Postgres (pgvector) store"

    def _run(self, query: str):
        jd_text = query.strip()
        if not jd_text:
            return "JD is empty."

        # Create embedding and extract skills
        jd_emb = embedding_for(jd_text)
        jd_skills = extract_skills(jd_text)

        # Generate unique ID
        job_id = str(uuid4())

        # Store into Postgres
        add_job(job_id, jd_text, jd_emb, jd_skills)

        return f"JD added successfully with ID: {job_id}"

    async def _arun(self, query: str):
        return self._run(query)
