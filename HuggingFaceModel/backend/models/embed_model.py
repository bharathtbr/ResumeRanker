from sentence_transformers import SentenceTransformer

class EmbedModel:
    def __init__(self, model_name="all-MiniLM-L6-v2"):
        # Keep this lightweight; used for explicit encoding when needed
        self.model = SentenceTransformer(model_name)

    def encode(self, text: str, normalize: bool = True):
        return self.model.encode([text], normalize_embeddings=normalize)[0].tolist()


# Singleton instance (so we don't reload the model every call)
_model_instance = EmbedModel()

def embedding_for(text: str):
    """
    Utility function to quickly embed a text.
    Other modules/tools can import and call this.
    """
    return _model_instance.encode(text)
