import os
import sys
from sqlmodel import Session, create_engine, text

# Add parent dir to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import engine

def migrate():
    with Session(engine) as session:
        print("Migrating: Adding compliance_flag to interview_reviews...")
        try:
            session.exec(text("ALTER TABLE interview_reviews ADD COLUMN compliance_flag BOOLEAN DEFAULT FALSE"))
            session.commit()
            print("Migration successful.")
        except Exception as e:
            print(f"Migration failed (maybe column exists?): {e}")

if __name__ == "__main__":
    migrate()
