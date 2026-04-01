import os
from sqlalchemy import text
from database import engine, Base

def migrate():
    print("Running phase 4 migrations...")
    # Import models so Base metadata is populated
    import app.models
    
    # 1. Create any missing tables (ZoneFlair, ZoneBan)
    Base.metadata.create_all(bind=engine)
    print("Created new tables (if they didn't exist)")

    with engine.begin() as conn:
        try:
            conn.execute(text("ALTER TABLE posts ADD COLUMN is_pinned BOOLEAN DEFAULT FALSE"))
            print("Added is_pinned to posts")
        except Exception as e:
            print(f"Skipped is_pinned: {e}")
            
        try:
            conn.execute(text("ALTER TABLE posts ADD COLUMN flair_id INTEGER REFERENCES zone_flairs(id) ON DELETE SET NULL"))
            print("Added flair_id to posts")
        except Exception as e:
            print(f"Skipped flair_id: {e}")
            
        try:
            conn.execute(text("ALTER TABLE comments ADD COLUMN parent_id INTEGER REFERENCES comments(id) ON DELETE CASCADE"))
            print("Added parent_id to comments")
        except Exception as e:
            print(f"Skipped parent_id: {e}")

if __name__ == "__main__":
    migrate()
