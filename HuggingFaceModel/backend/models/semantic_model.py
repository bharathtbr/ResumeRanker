from sentence_transformers import SentenceTransformer, util

# Use same model for semantic similarity
model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
