from fastapi import APIRouter, Depends, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from typing import List
import os
from app.database import get_session
from app.models import Candidate, Interview, QuestionSet, Question, InterviewReview
from app.routers.admin import get_current_username
from app.services.notification import make_outbound_call
import datetime

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

@router.post("/debug/create_test_call", summary="デバッグ: テスト架電実行", description="指定された3つの質問でテストユーザー(03-6240-9373)に即時架電します。")
async def debug_create_test_call(session: Session = Depends(get_session)):
    # 1. Create/Get Question Set
    qs_name = "クリエイター面接"
    q_set = session.exec(select(QuestionSet).where(QuestionSet.name == qs_name)).first()
    if not q_set:
        q_set = QuestionSet(name=qs_name, description="デザイナー・クリエイター向け（テスト用）")
        session.add(q_set)
        session.commit()
        session.refresh(q_set)
    
    # 2. Update Questions (Idempotent: delete existing for this set and recreate)
    # Clear existing questions for this set
    existing_qs = session.exec(select(Question).where(Question.set_id == q_set.id)).all()
    for eq in existing_qs:
        session.delete(eq)
    session.commit()

    questions_text = [
        "弊社を希望した志望動機を教えてください",
        "Photoshopやillustratorは使用したことがありますか、ある場合はどの程度出来るかを教えてください",
        "AIなどは普段使用していますが、使用している場合はどういったことに使っているかを教えてください"
    ]
    
    for i, text in enumerate(questions_text):
        q = Question(set_id=q_set.id, text=text, order=i+1, max_duration=60)
        session.add(q)
    session.commit()

    # 3. Create/Get Candidate
    phone = "0362409373" # As requested
    candidate = session.exec(select(Candidate).where(Candidate.phone == phone)).first()
    if not candidate:
        import uuid
        token = str(uuid.uuid4())
        candidate = Candidate(name="テスト ユーザー", kana="テスト ユーザー", phone=phone, email="test_call@example.com", token=token, question_set_id=q_set.id)
        session.add(candidate)
    else:
        candidate.question_set_id = q_set.id
        session.add(candidate)
    session.commit()
    session.refresh(candidate)

    # 4. Create Interview (Scheduled NOW)
    interview = Interview(
        candidate_id=candidate.id,
        reservation_time=datetime.datetime.utcnow(),
        status="scheduled"
    )
    session.add(interview)
    session.commit()
    session.refresh(interview)
    
    # 5. Execute Call
    sid = make_outbound_call(phone, interview.id)
    if sid:
        interview.status = "calling"
        session.add(interview)
        session.commit()
        return RedirectResponse(url="/admin/interviews_ui", status_code=303)
    else:
        # If calling fails (e.g. no creds even on server?), revert or show error
        # But we redirect to see the status "scheduled" (and maybe retry logic picks it up if it wasn't manual trigger, but manual trigger expects immediate)
        return HTMLResponse("Call initiation failed. Check server logs/credentials.", status_code=500)

@router.get("/debug/call", response_class=HTMLResponse, summary="デバッグ架電ページ", description="任意の番号と質問でテスト架電を行うフォームを表示します。")
async def debug_call_page(request: Request):
    return templates.TemplateResponse("admin/debug_call.html", {
        "request": request,
        "active_page": "debug"
    })

@router.post("/debug/call", summary="デバッグ架電実行")
async def debug_call_action(
    phone: str = Form(...),
    questions: List[str] = Form(...),
    session: Session = Depends(get_session)
):
    # Retrieve dynamic list of questions
    # FastAPI Form handles duplicate keys as list if defined as List[str]
    
    # 1. Setup Question Set (as before)
    qs_name = "Debug_Manual_Call"
    q_set = session.exec(select(QuestionSet).where(QuestionSet.name == qs_name)).first()
    if not q_set:
        q_set = QuestionSet(name=qs_name, description="手動デバッグ用")
        session.add(q_set)
        session.commit()
        session.refresh(q_set)
    
    # 2. Register Questions
    existing_qs = session.exec(select(Question).where(Question.set_id == q_set.id)).all()
    for eq in existing_qs:
        session.delete(eq)
    session.commit()
    
    # questions is now a list
    for i, txt in enumerate(questions):
        if txt.strip():
            session.add(Question(set_id=q_set.id, text=txt, order=i+1))
    session.commit()
    
    # 3. Setup Candidate & Phone Validation
    # Twilio requires E.164 (+81...)
    # User input "0362409373". We need to convert 03 -> +813
    clean_phone = phone.replace("-", "").replace(" ", "")
    
    # Simple JP logic: starts with 0 -> replace with +81, remove leading 0
    if clean_phone.startswith("0"):
        clean_phone = "+81" + clean_phone[1:]
    
    candidate = session.exec(select(Candidate).where(Candidate.phone == clean_phone)).first()
    if not candidate:
        import uuid
        token = str(uuid.uuid4())
        candidate = Candidate(name=f"Debug User ({clean_phone})", phone=clean_phone, email="debug@example.com", token=token, question_set_id=q_set.id)
        session.add(candidate)
    else:
        candidate.question_set_id = q_set.id
        candidate.name = f"Debug User ({clean_phone})" 
        session.add(candidate)
    session.commit()
    session.refresh(candidate)
    
    # 4. Schedule Interview (Now)
    interview = Interview(
        candidate_id=candidate.id,
        reservation_time=datetime.datetime.utcnow(),
        status="scheduled"
    )
    session.add(interview)
    session.commit()
    session.refresh(interview)
    
    # 5. Call
    sid = make_outbound_call(clean_phone, interview.id)
    
    if sid:
        interview.status = "calling"
        session.add(interview)
        session.commit()
        # Redirect to interview detail to see logs
        return RedirectResponse(url=f"/admin/interviews_ui/{interview.id}", status_code=303)
    else:
        return HTMLResponse(f"<h3>Call Failed</h3><p>Could not initiate call to {clean_phone}. Check server logs.</p><a href='/admin/debug/call'>Back</a>", status_code=500)

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
