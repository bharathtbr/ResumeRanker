from fastapi import APIRouter
import os, json
from typing import Optional
from sentence_transformers import SentenceTransformer, InputExample, losses
from torch.utils.data import DataLoader
from backend.vectorstore.resume_store import get_all_resumes, add_resume  # pgvector functions
from backend.models.embed_model import EmbedModel

FINE_TUNED_DIR = "models/fine_tuned"
FEEDBACK_FILE = "data/feedback.jsonl"

train_router = APIRouter()

# Initialize base model
model = EmbedModel().model

@train_router.post("/train")
async def train_model(epochs: Optional[int] = 1):
    """
    Fine-tune embeddings using labeled feedback and update all resume embeddings in pgvector.
    """
    global model  # <-- Move this to the top

    if not os.path.exists(FEEDBACK_FILE):
        return {"status": "no feedback to train"}

    # -------------------------
    # Load feedback examples
    # -------------------------
    examples = []
    with open(FEEDBACK_FILE, "r", encoding="utf-8") as f:
        for line in f:
            obj = json.loads(line.strip())
            jd = obj["jd"]
            resume_chunk = obj["resume_chunk"]
            label = float(obj["label"])
            examples.append(InputExample(texts=[jd, resume_chunk], label=label))

    if not examples:
        return {"status": "no training examples"}

    # -------------------------
    # Train model
    # -------------------------
    train_dataloader = DataLoader(examples, shuffle=True, batch_size=8)
    train_loss = losses.CosineSimilarityLoss(model)
    model.fit(
        train_objectives=[(train_dataloader, train_loss)],
        epochs=epochs,
        warmup_steps=10,
        output_path=FINE_TUNED_DIR
    )

    # Reload fine-tuned model
    model = SentenceTransformer(FINE_TUNED_DIR)

    # -------------------------
    # Re-embed all resumes in pgvector DB
    # -------------------------
    resumes = get_all_resumes()
    for resume in resumes:
        new_emb = model.encode([resume.text], normalize_embeddings=True)[0].tolist()
        add_resume(resume.filename,resume.skills, resume.text)

    return {"status": "trained", "examples": len(examples), "resumes_updated": len(resumes)}
