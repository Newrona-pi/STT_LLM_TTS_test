from fastapi import APIRouter, Depends, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from typing import List
import os
from app.database import get_session
from app.models import Candidate, Interview, QuestionSet, InterviewReview
from app.routers.admin import get_current_username

from pathlib import Path

router = APIRouter(prefix="/admin", tags=["admin_view"], dependencies=[Depends(get_current_username)])

# Resolve absolute path to templates
BASE_DIR = Path(__file__).resolve().parent.parent # points to 'app' directory
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, session: Session = Depends(get_session)):
    # Stats
    total_candidates = session.exec(select(Candidate)).all()
    # Today interviews (UTC for now, ideally JST logic)
    # Simple count for MVP
    total_interviews = session.exec(select(Interview)).all()
    
    stats = {
        "total_candidates": len(total_candidates),
        "today_interviews": len(total_interviews) # Placeholder logic
    }
    
    return templates.TemplateResponse("admin/dashboard.html", {
        "request": request, 
        "stats": stats,
        "active_page": "dashboard"
    })

@router.get("/help", response_class=HTMLResponse)
async def help_page(request: Request):
    return templates.TemplateResponse("admin/help.html", {
        "request": request,
        "active_page": "help"
    })

@router.get("/candidates_ui", response_class=HTMLResponse)
async def list_candidates_ui(request: Request, session: Session = Depends(get_session)):
    candidates = session.exec(select(Candidate)).all()
    base_url = os.environ.get("BASE_URL", str(request.base_url).rstrip("/"))
    
    return templates.TemplateResponse("admin/candidates_list.html", {
        "request": request,
        "candidates": candidates,
        "base_url": base_url,
        "active_page": "candidates"
    })

@router.post("/candidates_ui/upload")
async def upload_candidates_ui(file: UploadFile = File(...), session: Session = Depends(get_session)):
    # Reuse logic or copy-paste (Importing logic from admin.py is cleaner but function signature varies)
    # Let's simple copy logic for MVP to avoid circular dependencies if imports are messy
    import csv
    import codecs
    import uuid
    
    csvReader = csv.reader(codecs.iterdecode(file.file, 'utf-8'), delimiter=',')
    header = next(csvReader, None)
    
    for row in csvReader:
        if len(row) >= 3:
            name = row[0].strip()
            phone = row[1].strip()
            email = row[2].strip()
            
            q_set_id = None
            if len(row) >= 4 and row[3].strip():
                qs_name = row[3].strip()
                q_set = session.exec(select(QuestionSet).where(QuestionSet.name == qs_name)).first()
                if q_set:
                    q_set_id = q_set.id
            
            token = str(uuid.uuid4())
            candidate = Candidate(name=name, phone=phone, email=email, token=token, question_set_id=q_set_id)
            session.add(candidate)
    
    session.commit()
    session.commit()
    return RedirectResponse(url="/admin/candidates_ui", status_code=303)

@router.post("/candidates_ui/create")
async def create_candidate_ui(
    name: str = Form(...),
    phone: str = Form(...),
    email: str = Form(...),
    session: Session = Depends(get_session)
):
    import uuid
    # Logic similar to upload but for single entry
    token = str(uuid.uuid4())
    # Default question set logic if needed, or None
    candidate = Candidate(name=name, phone=phone, email=email, token=token)
    session.add(candidate)
    session.commit()
    return RedirectResponse(url="/admin/candidates_ui", status_code=303)

@router.get("/interviews_ui", response_class=HTMLResponse)
async def list_interviews_ui(request: Request, session: Session = Depends(get_session)):
    import datetime
    # Get all interviews sorted by time (descending)
    interviews = session.exec(select(Interview).order_by(Interview.reservation_time.desc())).all()
    
    now = datetime.datetime.now()
    
    # Split into future (including today) and past
    # Condition: Future/Today is reservation_time >= (Today 00:00:00) ??
    # User said: "Today ~ Future" for Schedule, "Past" for History (yesterday and before).
    # However, usually "Scheduled" means "Not yet happened". 
    # But user specifically said "Today ~ Future reservation".
    # Let's define "Past" as "reservation_time.date() < today.date()".
    # And "Future/Today" as "reservation_time.date() >= today.date()".
    
    today = now.date()
    
    scheduled_interviews = []
    past_interviews = []
    
    for i in interviews:
        # parsed datetime might be needed if it's string, but SQLModel usually handles it.
        # Check if i.reservation_time is datetime
        r_time = i.reservation_time
        if isinstance(r_time, str):
            r_time = datetime.datetime.fromisoformat(r_time)
            
        if r_time.date() >= today:
            scheduled_interviews.append(i)
        else:
            past_interviews.append(i)
            
    # Sort scheduled by ASC (nearest first)
    scheduled_interviews.sort(key=lambda x: x.reservation_time)
    # Sort past by DESC (most recent first) - already sorted by query but filtering might mess up if mixed
    past_interviews.sort(key=lambda x: x.reservation_time, reverse=True)

    return templates.TemplateResponse("admin/interviews_list.html", {
        "request": request,
        "interviews": interviews, # Keeping this for legacy if needed, but template will use new ones
        "scheduled_interviews": scheduled_interviews,
        "past_interviews": past_interviews,
        "active_page": "interviews"
    })

@router.get("/interviews_ui/{id}", response_class=HTMLResponse)
async def interview_detail_ui(request: Request, id: int, session: Session = Depends(get_session)):
    interview = session.get(Interview, id)
    if not interview:
        return HTMLResponse("Interview not found", status_code=404)
        
    reviews = session.exec(select(InterviewReview).where(InterviewReview.interview_id == id).order_by(InterviewReview.question_id)).all()
    
    return templates.TemplateResponse("admin/interview_detail.html", {
        "request": request,
        "interview": interview,
        "reviews": reviews,
        "active_page": "interviews"
    })
