from sentence_transformers import SentenceTransformer
import torch

class MLService:
    _model = None

    @classmethod
    def get_model(cls):
        """Lazy load the sentence transformer model."""
        if cls._model is None:
            print("  [MLService] Loading all-MiniLM-L6-v2...")
            # Using CPU for standard web server thread safety and efficiency
            cls._model = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")
        return cls._model

    @classmethod
    def encode_query(cls, query: str):
        """Encode a single search query into a vector."""
        model = cls.get_model()
        return model.encode(query, convert_to_numpy=True)
