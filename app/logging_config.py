import logging
import sys
from config import settings

def setup_logging():
    # Define log format
    log_format = (
        "[%(asctime)s] %(levelname)s [%(name)s:%(lineno)s] %(message)s"
    )
    
    # Configure root logger
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        stream=sys.stdout,
        force=True
    )
    
    # Set levels for noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    
    logger = logging.getLogger(settings.APP_NAME)
    logger.info(f"Logging initialized for {settings.APP_NAME}")
    return logger

# Singleton instance
logger = setup_logging()
