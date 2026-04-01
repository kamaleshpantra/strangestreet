import os
from sqlalchemy import text
from database import engine

def migrate():
    with engine.begin() as conn:
        try:
            conn.execute(text("ALTER TABLE users ADD COLUMN public_key TEXT"))
            print("Added public_key")
        except Exception as e:
            print(f"Skipped public_key: {e}")
            
        try:
            conn.execute(text("ALTER TABLE users ADD COLUMN street_coins INTEGER DEFAULT 0"))
            print("Added street_coins")
        except Exception as e:
            print(f"Skipped street_coins: {e}")
            
        try:
            # SQLite uses integer for boolean, pg uses boolean
            try:
                conn.execute(text("ALTER TABLE users ADD COLUMN is_premium BOOLEAN DEFAULT FALSE"))
            except:
                conn.execute(text("ALTER TABLE users ADD COLUMN is_premium INTEGER DEFAULT 0"))
            print("Added is_premium")
        except Exception as e:
            print(f"Skipped is_premium: {e}")

if __name__ == "__main__":
    migrate()
