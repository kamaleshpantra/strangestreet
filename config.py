from pydantic_settings import BaseSettings
from dotenv import load_dotenv
import os

load_dotenv()

class Settings(BaseSettings):
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/nexusai")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 10080  # 7 days
    APP_NAME: str = "Strange Street"

    # Debug mode: set to False in production to hide tracebacks
    DEBUG: bool = os.getenv("DEBUG", "true").lower() in ("true", "1", "yes")

    # Upload limits
    MAX_UPLOAD_SIZE_MB: int = int(os.getenv("MAX_UPLOAD_SIZE_MB", "10"))

    # Cloudinary Settings
    CLOUDINARY_CLOUD_NAME: str = os.getenv("CLOUDINARY_CLOUD_NAME", "")
    CLOUDINARY_API_KEY: str = os.getenv("CLOUDINARY_API_KEY", "")
    CLOUDINARY_API_SECRET: str = os.getenv("CLOUDINARY_API_SECRET", "")

    def validate_secrets(self):
        """Fail fast if critical secrets are missing in production."""
        if not self.DEBUG and not self.SECRET_KEY:
            raise ValueError(
                "FATAL: SECRET_KEY is not set. "
                "Set SECRET_KEY in .env or environment variables before running in production."
            )
        if not self.SECRET_KEY:
            # Dev fallback with loud warning
            import warnings
            warnings.warn(
                "⚠️  SECRET_KEY not set — using insecure dev default. "
                "DO NOT use this in production!",
                stacklevel=2,
            )
            self.SECRET_KEY = "dev-only-insecure-key-change-me"


settings = Settings()
settings.validate_secrets()
