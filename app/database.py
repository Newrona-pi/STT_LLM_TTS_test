from sqlmodel import SQLModel, create_engine, Session
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL")

# Handle SQLite fallback for local testing if needed, or enforce Postgres
if not DATABASE_URL:
    # Default to sqlite for local dev if not provided (though instructions say utilize existing DB)
    sqlite_file_name = "database.db"
    DATABASE_URL = f"sqlite:///{sqlite_file_name}"

# Postgres connection args (if needed for ssl)
connect_args = {}
if "postgresql" in DATABASE_URL:
    # Railway/Heroku usually requires SSL
    # connect_args = {"check_same_thread": False} # Not for postgres
    pass
else:
    connect_args = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, echo=False, connect_args=connect_args)

def get_session():
    with Session(engine) as session:
        yield session

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)
