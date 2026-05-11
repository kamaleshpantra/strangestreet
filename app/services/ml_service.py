import os


class MLService:
    _model = None
    _disabled = os.getenv("DISABLE_ML_MODEL", "").lower() in ("true", "1", "yes")

    @classmethod
    def get_model(cls):
        """Lazy load the sentence transformer model."""
        if cls._disabled:
            return None  # Skip on memory-constrained environments (Render free tier)
        if cls._model is None:
            from sentence_transformers import SentenceTransformer
            import torch
            print("  [MLService] Loading all-MiniLM-L6-v2...")
            # Using CPU for standard web server thread safety and efficiency
            cls._model = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")
        return cls._model

    @classmethod
    def encode_query(cls, query: str):
        """Encode a single search query into a vector. Returns None when ML is disabled."""
        model = cls.get_model()
        if model is None:
            return None
        return model.encode(query, convert_to_numpy=True)
