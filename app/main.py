from fastapi import FastAPI
from app.database import create_db_and_tables
from app.routers import admin, candidate, voice
from app.services.scheduler import start_scheduler
import os

app = FastAPI(title="AI Interview System (Logic C)")

app.include_router(admin.router)
app.include_router(candidate.router)
app.include_router(voice.router)

@app.on_event("startup")
def on_startup():
    create_db_and_tables()
    start_scheduler()

@app.get("/")
def read_root():
    return {"message": "AI Interview System (Logic C) is running"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    # Production: reload=False
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=False)
