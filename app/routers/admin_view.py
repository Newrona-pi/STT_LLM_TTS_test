from fastapi import APIRouter, Depends, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from typing import List
import os
from app.database import get_session
from app.models import Candidate, Interview, QuestionSet, InterviewReview
from app.routers.admin import get_current_username

router = APIRouter(prefix="/admin", tags=["admin_view"], dependencies=[Depends(get_current_username)])

templates = Jinja2Templates(directory="app/templates")

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
    return RedirectResponse(url="/admin/candidates_ui", status_code=303)

@router.get("/interviews_ui", response_class=HTMLResponse)
async def list_interviews_ui(request: Request, session: Session = Depends(get_session)):
    import datetime
    interviews = session.exec(select(Interview).order_by(Interview.reservation_time.desc())).all()
    return templates.TemplateResponse("admin/interviews_list.html", {
        "request": request,
        "interviews": interviews,
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
