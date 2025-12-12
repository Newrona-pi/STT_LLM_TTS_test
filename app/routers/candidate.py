from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from app.database import get_session
from app.models import Candidate, Interview
from app.services.notification import send_email, send_sms
from datetime import datetime
import os

router = APIRouter(tags=["candidate"])

# Setup templates
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

@router.get("/book", response_class=HTMLResponse)
def show_booking_page(request: Request, token: str, session: Session = Depends(get_session)):
    candidate = session.exec(select(Candidate).where(Candidate.token == token)).first()
    if not candidate:
        return templates.TemplateResponse("error.html", {"request": request, "message": "無効なトークンです。"}, status_code=404)
    
    # Get existing interview if any
    interview = session.exec(select(Interview).where(Interview.candidate_id == candidate.id)).order_by(Interview.reservation_time.desc()).first()
    
    return templates.TemplateResponse("booking.html", {
        "request": request,
        "candidate": candidate,
        "existing_interview": interview,
        "token": token
    })

@router.post("/book", response_class=HTMLResponse)
def submit_booking(
    request: Request,
    token: str = Form(...),
    date: str = Form(...),
    time: str = Form(...),
    session: Session = Depends(get_session)
):
    candidate = session.exec(select(Candidate).where(Candidate.token == token)).first()
    if not candidate:
        return templates.TemplateResponse("error.html", {"request": request, "message": "無効なトークンです。"}, status_code=404)
    
    # Parse datetime
    try:
        reservation_dt = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
    except ValueError:
        return templates.TemplateResponse("error.html", {"request": request, "message": "日付形式が不正です。"}, status_code=400)
    
    # Create or update interview
    # Logic C: New interview overwrites logic, but Requirement says "Update (overwrite) but keep history"
    # Keeping history means creating new record or logging change.
    # Implementation Plan says "interviews" table has status.
    # Simple approach: Create new active interview, mark old as cancelled is cleaner, or update existing.
    # Requirement: "変更履歴はDBに残し管理画面で閲覧可能"
    # Let's create a new record for every booking to keep history simple.
    
    # Cancel old scheduled interviews
    old_interviews = session.exec(select(Interview).where(Interview.candidate_id == candidate.id, Interview.status == "scheduled")).all()
    for old in old_interviews:
        old.status = "cancelled_by_update"
        session.add(old)
        
    # Create new interview
    interview = Interview(
        candidate_id=candidate.id,
        reservation_time=reservation_dt,
        status="scheduled"
    )
    session.add(interview)
    
    # Update candidate status
    candidate.status = "automated" # or 'scheduled'
    session.add(candidate)
    
    session.commit()
    session.refresh(interview)
    
    # Notifications
    msg_body = f"{candidate.name}様\n\nAI一次面接の予約を承りました。\n日時: {reservation_dt.strftime('%Y/%m/%d %H:%M')}\n\n予定日時にAIからお電話します。\n変更する場合は同じURLからアクセスしてください。"
    
    send_email(candidate.email, "【パインズ】AI面接予約完了のお知らせ", msg_body, candidate.id, session)
    send_sms(candidate.phone, msg_body, candidate.id, session)
    
    return templates.TemplateResponse("success.html", {
        "request": request,
        "candidate": candidate,
        "reservation_time": reservation_dt
    })
