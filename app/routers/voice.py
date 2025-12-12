from fastapi import APIRouter, Request, Depends, HTTPException, BackgroundTasks, Form, Query
from fastapi.responses import Response
from sqlmodel import Session, select
from twilio.twiml.voice_response import VoiceResponse
from app.database import get_session
from app.models import Interview, Candidate, QuestionSet, Question, InterviewReview
from app.services.stt_service import transcribe_audio_url
from typing import List, Optional
import datetime
from datetime import timedelta

router = APIRouter(prefix="/voice", tags=["voice"])

def get_voice_response():
    resp = VoiceResponse()
    return resp

def process_stt_background(review_id: int, recording_url: str):
    # This function will run in background
    from app.database import engine
    from sqlmodel import Session
    
    with Session(engine) as session:
        review = session.get(InterviewReview, review_id)
        if review:
            text = transcribe_audio_url(recording_url)
            review.transcript = text
            session.add(review)
            session.commit()
            print(f"[INFO] STT Completed for Review {review_id}")

@router.post("/call")
async def start_call(
    interview_id: int = Query(...),
    session: Session = Depends(get_session)
):
    interview = session.get(Interview, interview_id)
    if not interview:
        return Response(content=str(VoiceResponse().hangup()), media_type="application/xml")
    
    # Init snapshot if empty
    if not interview.session_snapshot:
        candidate = interview.candidate
        q_set_id = candidate.question_set_id
        
        # If no set assigned, use default or first one
        if not q_set_id:
            qs = session.exec(select(QuestionSet)).first()
            if qs:
                q_set_id = qs.id
        
        questions = []
        if q_set_id:
            questions = session.exec(select(Question).where(Question.set_id == q_set_id).order_by(Question.order)).all()
        
        # Create snapshot list
        snapshot = []
        for q in questions:
            snapshot.append({
                "id": q.id,
                "text": q.text,
                "max_duration": q.max_duration
            })
        
        interview.session_snapshot = snapshot
        interview.status = "in_progress"
        session.add(interview)
        session.commit()
        session.refresh(interview)
    
    # Resume greeting logic if resumed?
    # Logic: if status was interrupted or resume_count > 0
    greeting_done = False
    
    resp = VoiceResponse()
    if interview.resume_count > 0:
        resp.say("お電話が途中できれましたので、続きから面接を行います。", language="ja-JP")
        # Check last completed question?
        # Logic is handled in redirect.
    else:
        resp.say("株式会社パインズです。", language="ja-JP", voice="alice") 
        resp.pause(length=1)
        resp.say("ただいまより、AIによる一次面接を行います。所要時間は15分程度です。", language="ja-JP", voice="alice")
        resp.say("通話内容は、録音、および文字起こしされますので、あらかじめご了承ください。", language="ja-JP", voice="alice")
    
    # Find next question index
    next_q_index = 0
    if interview.last_completed_q_id:
        for idx, q in enumerate(interview.session_snapshot):
            if q["id"] == interview.last_completed_q_id:
                next_q_index = idx + 1
                break
    
    resp.redirect(f"/voice/question?interview_id={interview.id}&q_index={next_q_index}")
    
    return Response(content=str(resp), media_type="application/xml")

@router.post("/question")
async def ask_question(
    interview_id: int = Query(...),
    q_index: int = Query(...),
    session: Session = Depends(get_session)
):
    interview = session.get(Interview, interview_id)
    if not interview or not interview.session_snapshot:
        resp = VoiceResponse()
        resp.say("エラーが発生しました。終了します。", language="ja-JP")
        resp.hangup()
        return Response(content=str(resp), media_type="application/xml")
    
    snapshot = interview.session_snapshot
    total_questions = len(snapshot)
    
    # Check if finished
    if q_index >= total_questions:
        resp = VoiceResponse()
        resp.redirect(f"/voice/end?interview_id={interview.id}")
        return Response(content=str(resp), media_type="application/xml")
    
    question = snapshot[q_index]
    remaining = total_questions - q_index
    
    resp = VoiceResponse()
    
    # カウント告知
    if remaining == 3:
        resp.say("残り3点です。", language="ja-JP")
    elif remaining == 2:
        resp.say("残り2点です。", language="ja-JP")
    elif remaining == 1:
        resp.say("これが最後の質問です。", language="ja-JP")
        
    # Question text
    resp.say(question["text"], language="ja-JP")
    resp.pause(length=1)
    
    # Instruction
    resp.say("3分以内で回答してください。話し終えたら、以上です、と言って待つか、無言で終了してください。", language="ja-JP")
    
    # Record
    resp.record(
        action=f"/voice/record?interview_id={interview.id}&q_index={q_index}",
        max_length=question.get("max_duration", 180),
        finish_on_key="*#", 
        timeout=5, 
        trim="trim-silence"
    )
    
    # Fallback
    resp.redirect(f"/voice/record?interview_id={interview.id}&q_index={q_index}") 
    
    return Response(content=str(resp), media_type="application/xml")

@router.post("/record")
async def save_recording(
    background_tasks: BackgroundTasks,
    interview_id: int = Query(...),
    q_index: int = Query(...),
    RecordingUrl: Optional[str] = Form(None),
    RecordingDuration: Optional[str] = Form(None),
    session: Session = Depends(get_session)
):
    interview = session.get(Interview, interview_id)
    if interview and interview.session_snapshot and 0 <= q_index < len(interview.session_snapshot):
        question = interview.session_snapshot[q_index]
        
        # Save Review
        review = InterviewReview(
            interview_id=interview.id,
            question_id=question["id"],
            question_text=question["text"],
            recording_url=RecordingUrl,
            duration=int(RecordingDuration) if RecordingDuration else 0
        )
        session.add(review)
        
        # Update progress
        interview.last_completed_q_id = question["id"]
        session.add(interview)
        
        session.commit()
        session.refresh(review)
        
        # Trigger STT
        if RecordingUrl:
            background_tasks.add_task(process_stt_background, review.id, RecordingUrl)
    
    # Move to next
    next_index = q_index + 1
    resp = VoiceResponse()
    resp.redirect(f"/voice/question?interview_id={interview_id}&q_index={next_index}")
    
    return Response(content=str(resp), media_type="application/xml")

@router.post("/end")
async def end_call(
    interview_id: int = Query(...),
    session: Session = Depends(get_session)
):
    interview = session.get(Interview, interview_id)
    if interview:
        interview.status = "completed"
        session.add(interview)
        session.commit()
        
    resp = VoiceResponse()
    resp.say("すべての質問は以上です。", language="ja-JP")
    resp.say("本日はお忙しい中お時間をいただき、ありがとうございました。", language="ja-JP")
    resp.say("面接の結果は、通過された方にのみ、7営業日前後にご連絡いたします。", language="ja-JP")
    resp.say("それでは、失礼いたします。", language="ja-JP")
    resp.hangup()
    
    return Response(content=str(resp), media_type="application/xml")


@router.post("/status")
async def call_status(
    interview_id: int = Query(...),
    CallStatus: str = Form(...),
    session: Session = Depends(get_session)
):
    interview = session.get(Interview, interview_id)
    if not interview:
        return {"message": "Interview not found"}
        
    print(f"[INFO] CallStatus for Interview {interview.id}: {CallStatus}")
    
    if CallStatus in ["completed"]:
        if interview.status != "completed":
            # Check if really completed or just call ended
            if interview.session_snapshot and interview.last_completed_q_id:
                last_q = interview.session_snapshot[-1]
                if last_q["id"] == interview.last_completed_q_id:
                     interview.status = "completed"
                else:
                     # Resume Trigger
                     if interview.resume_count < 3:
                         interview.resume_count += 1
                         interview.status = "scheduled"
                         interview.reservation_time = datetime.datetime.utcnow() + timedelta(minutes=1)
                         print(f"[INFO] Scheduling RESUME for Interview {interview.id}. Count: {interview.resume_count}")
                     else:
                         interview.status = "failed"
            else:
                 # Early hangup (no questions answered)
                 if interview.resume_count < 3:
                     interview.resume_count += 1
                     interview.status = "scheduled"
                     interview.reservation_time = datetime.datetime.utcnow() + timedelta(minutes=1)
                     print(f"[INFO] Scheduling RESUME associated with early hangup {interview.id}.")
                 else:
                     interview.status = "failed"
                     
    elif CallStatus in ["busy", "no-answer", "failed"]:
        # Retry Logic (Initial connection failure)
        # Update: User requested NO retry (1 call only)
        # if interview.retry_count < 3: (Original)
        if interview.retry_count < 0: # Disabled
            interview.retry_count += 1
            interview.status = "scheduled"
            interview.reservation_time = datetime.datetime.utcnow() + timedelta(minutes=2)
            print(f"[INFO] Scheduling RETRY for Interview {interview.id}. Count: {interview.retry_count}")
        else:
            interview.status = "failed"
            # Notify User
            from app.services.notification import send_sms, send_email
            candidate = interview.candidate
            msg = f"{candidate.name}様\n\nAI面接のお電話をしましたが、つながりませんでした。\n以下のURLから再度ご予約をお願いいたします。\nURL: {os.environ.get('BASE_URL', '')}/book?token={candidate.token}"  # Simplified
            send_sms(candidate.phone, msg, candidate.id, session)
            send_email(candidate.email, "【パインズ】AI面接 再予約のお願い", msg, candidate.id, session)
            
    session.add(interview)
    session.commit()
    
    return {"status": "ok"}
