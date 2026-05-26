# Compatibility bridge for database setup - forwards to core implementation
from app.core.database import Base, SessionLocal, engine, get_db
