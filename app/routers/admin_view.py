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


@router.get("/dashboard", response_class=HTMLResponse, summary="ダッシュボード表示", description="管理者ダッシュボードを表示します。")
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

@router.get("/candidates_ui", response_class=HTMLResponse, summary="候補者一覧表示", description="登録済みの候補者一覧を表示します。")
async def list_candidates_ui(request: Request, session: Session = Depends(get_session)):
    candidates = session.exec(select(Candidate)).all()
    base_url = os.environ.get("BASE_URL", str(request.base_url).rstrip("/"))
    
    return templates.TemplateResponse("admin/candidates_list.html", {
        "request": request,
        "candidates": candidates,
        "base_url": base_url,
        "active_page": "candidates"
    })

@router.post("/candidates_ui/upload", summary="候補者CSV一括登録", description="CSVファイルをアップロードして候補を一括登録します。")
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

    })

@router.post("/candidates_ui/create", summary="候補者手動登録", description="フォームから候補者を1件登録し、任意で招待メールを送信します。")
async def create_candidate_ui(
    name: str = Form(...),
    kana: str = Form(None),
    phone: str = Form(...),
    email: str = Form(...),
    send_invite: bool = Form(False),
    session: Session = Depends(get_session)
):
    import uuid
    from datetime import datetime
    from app.services.notification import send_email
    
    token = str(uuid.uuid4())
    candidate = Candidate(
        name=name, 
        kana=kana, 
        phone=phone, 
        email=email, 
        token=token,
        token_issued_at=datetime.utcnow() if send_invite else None,
        token_sent_type="manual_form" if send_invite else "none"
    )
    session.add(candidate)
    session.commit()
    session.refresh(candidate)
    
    if send_invite:
        base_url = os.environ.get("BASE_URL")
        # Fallback if BASE_URL not set (dev)
        if not base_url: 
             # We can't easily get request here without passing it, but let's try env first
             pass
             
        # Construct simplified message
        invite_url = f"{base_url}/book?token={token}" if base_url else f"(Setup BASE_URL)/book?token={token}"
        
        subject = "【面接予約】AI面接のご案内"
        body = f"{name}様\n\nAI一次面接のご案内です。\n以下のURLよりご都合の良い日時をご予約ください。\n\n予約URL: {invite_url}\n\nよろしくお願いいたします。"
        
        send_email(candidate.email, subject, body, candidate.id, session)
        
    return RedirectResponse(url="/admin/candidates_ui", status_code=303)

@router.get("/candidates_ui/{id}", response_class=HTMLResponse)
async def candidate_detail_ui(request: Request, id: int, session: Session = Depends(get_session)):
    candidate = session.get(Candidate, id)
    if not candidate:
        return HTMLResponse("Candidate not found", status_code=404)
        
    base_url = os.environ.get("BASE_URL", str(request.base_url).rstrip("/"))
    
    return templates.TemplateResponse("admin/candidate_detail.html", {
        "request": request,
        "candidate": candidate,
        "base_url": base_url,
        "active_page": "candidates"
    })

@router.post("/candidates_ui/{id}/resend_token")
async def resend_token(id: int, request: Request, session: Session = Depends(get_session)):
    import datetime
    from app.services.notification import send_email
    
    candidate = session.get(Candidate, id)
    if not candidate:
        return HTMLResponse("Candidate not found", status_code=404)
        
    base_url = os.environ.get("BASE_URL", str(request.base_url).rstrip("/"))
    invite_url = f"{base_url}/book?token={candidate.token}"
    
    subject = "【再送】AI面接のご案内"
    body = f"{candidate.name}様\n\n(再送) AI一次面接のご案内です。\n以下のURLよりご都合の良い日時をご予約ください。\n\n予約URL: {invite_url}\n\nよろしくお願いいたします。"
    
    sent = send_email(candidate.email, subject, body, candidate.id, session)
    
    if sent:
        candidate.token_issued_at = datetime.datetime.utcnow()
        candidate.token_sent_type = "manual_resend"
        session.add(candidate)
        session.commit()
    
    return RedirectResponse(url=f"/admin/candidates_ui/{id}", status_code=303)

@router.get("/interviews_ui", response_class=HTMLResponse, summary="面接履歴表示", description="面接の予約状況と履歴を表示します。")
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
    
    # Split interviews
    now = datetime.datetime.now()
    today = now.date()
    
    today_interviews = []
    future_interviews = []
    past_interviews = []
    
    for i in interviews:
        r_time = i.reservation_time
        if isinstance(r_time, str):
            r_time = datetime.datetime.fromisoformat(r_time)
            
        r_date = r_time.date()
        
        if r_date == today:
            today_interviews.append(i)
        elif r_date > today:
            future_interviews.append(i)
        else:
            past_interviews.append(i)
            
    # Sort
    today_interviews.sort(key=lambda x: x.reservation_time)
    future_interviews.sort(key=lambda x: x.reservation_time)
    past_interviews.sort(key=lambda x: x.reservation_time, reverse=True)

    return templates.TemplateResponse("admin/interviews_list.html", {
        "request": request,
        "interviews": interviews,
        "today_interviews": today_interviews,
        "future_interviews": future_interviews,
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
