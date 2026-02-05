"""
HuggingFace Generative Model for Skill Extraction
Uses local Flan-T5 or similar model instead of Groq
"""

from transformers import AutoTokenizer, AutoModelForSeq2SeqLM, pipeline
import torch

class SkillExtractionModel:
    """
    Local HuggingFace model for skill extraction
    Uses Flan-T5 (smaller, faster) or similar models
    """
    
    def __init__(self, model_name: str = "google/flan-t5-base"):
        """
        Initialize skill extraction model
        
        Options:
        - google/flan-t5-base (250M params, fast, good quality)
        - google/flan-t5-large (780M params, better quality, slower)
        - facebook/opt-1.3b (1.3B params, very good quality)
        """
        print(f"[SKILL_MODEL] Loading {model_name}...")
        
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"[SKILL_MODEL] Using device: {self.device}")
        
        # Load model and tokenizer
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForSeq2SeqLM.from_pretrained(model_name)
        self.model.to(self.device)
        
        print(f"[SKILL_MODEL] Model loaded successfully")
    
    def extract_skills_from_text(self, text: str, max_length: int = 512) -> str:
        """
        Extract skills using the model
        
        Args:
            text: Resume text (will be truncated if too long)
            max_length: Max input length
        
        Returns:
            Model response (needs JSON parsing)
        """
        
        # Truncate text if needed
        text = text[:10000]  # Keep reasonable size
        
        prompt = f"""Extract all technical skills from this resume and return as JSON list.
Include programming languages, frameworks, databases, cloud platforms, tools.

Resume:
{text}

Return JSON list of skills:"""
        
        # Tokenize
        inputs = self.tokenizer(
            prompt, 
            return_tensors="pt", 
            max_length=max_length,
            truncation=True
        ).to(self.device)
        
        # Generate
        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=500,
                temperature=0.1,
                do_sample=False
            )
        
        # Decode
        response = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
        return response.strip()


# Singleton
_skill_model = None

def get_skill_model() -> SkillExtractionModel:
    """Get or create skill extraction model"""
    global _skill_model
    if _skill_model is None:
        _skill_model = SkillExtractionModel()
    return _skill_model


def extract_skills_with_hf(text: str) -> str:
    """Quick utility to extract skills"""
    model = get_skill_model()
    return model.extract_skills_from_text(text)
