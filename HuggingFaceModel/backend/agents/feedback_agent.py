from fastapi import APIRouter
from pydantic import BaseModel
import os, json

FEEDBACK_FILE = "data/feedback.json"
feedback_router = APIRouter()

class FeedbackRequest(BaseModel):
    jd: str
    resume_chunk: str
    label: int

@feedback_router.post("/feedback")
async def feedback(req: FeedbackRequest):
    rec = {"jd": req.jd, "resume_chunk": req.resume_chunk, "label": int(req.label)}
    os.makedirs(os.path.dirname(FEEDBACK_FILE), exist_ok=True)
    with open(FEEDBACK_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    return {"status": "recorded"}
