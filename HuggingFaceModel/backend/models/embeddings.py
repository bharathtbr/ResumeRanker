"""
HuggingFace Embedding Model Wrapper
Uses existing embed_model from models/
"""

from backend.models.embed_model import EmbedModel, embedding_for
import numpy as np
from typing import List, Union

# Use the singleton from embed_model
_embed_model = EmbedModel()

class EmbeddingModel:
    """
    Wrapper for consistency with other parts of the codebase
    Uses the existing embed_model.py
    """
    
    def __init__(self):
        self.model = _embed_model
        self.dimension = 384
        print(f"[EMBED] Using existing embed_model, dimension: {self.dimension}")
    
    def encode(self, text: Union[str, List[str]], normalize: bool = True) -> Union[List[float], List[List[float]]]:
        """Generate embeddings"""
        if isinstance(text, str):
            return self.model.encode(text, normalize=normalize)
        else:
            # Batch encoding
            return [self.model.encode(t, normalize=normalize) for t in text]
    
    def similarity(self, emb1: List[float], emb2: List[float]) -> float:
        """Calculate cosine similarity"""
        arr1 = np.array(emb1)
        arr2 = np.array(emb2)
        
        dot_product = np.dot(arr1, arr2)
        norm1 = np.linalg.norm(arr1)
        norm2 = np.linalg.norm(arr2)
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        similarity = dot_product / (norm1 * norm2)
        return float(max(0.0, min(1.0, similarity)))


# Singleton instance
_model_instance = None

def get_embedding_model() -> EmbeddingModel:
    """Get or create singleton embedding model"""
    global _model_instance
    if _model_instance is None:
        _model_instance = EmbeddingModel()
    return _model_instance


def embed_text(text: str) -> List[float]:
    """Quick utility using existing embedding_for function"""
    return embedding_for(text)


def embed_batch(texts: List[str]) -> List[List[float]]:
    """Quick utility to embed multiple texts"""
    model = get_embedding_model()
    return model.encode(texts)


def calculate_similarity(text1: str, text2: str) -> float:
    """Calculate similarity between two texts"""
    model = get_embedding_model()
    emb1 = model.encode(text1)
    emb2 = model.encode(text2)
    return model.similarity(emb1, emb2)
