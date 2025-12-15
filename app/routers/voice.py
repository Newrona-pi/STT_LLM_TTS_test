from fastapi import APIRouter, Request, Depends, HTTPException, BackgroundTasks, Form, Query
from fastapi.responses import Response
from sqlmodel import Session, select
from twilio.twiml.voice_response import VoiceResponse, Gather
from app.database import get_session
from app.models import Interview, Candidate, QuestionSet, Question, InterviewReview
from app.services.stt_service import transcribe_audio_url
from app.services.llm_service import extract_topic
from typing import List, Optional
import datetime
from datetime import timedelta

router = APIRouter(prefix="/voice", tags=["voice"])

def process_stt_background(review_id: int, recording_url: str):
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
    
    # Init snapshot logic same as before...
    if not interview.session_snapshot:
        candidate = interview.candidate
        q_set_id = candidate.question_set_id
        if not q_set_id:
            qs = session.exec(select(QuestionSet)).first()
            if qs: q_set_id = qs.id
        questions = []
        if q_set_id:
            questions = session.exec(select(Question).where(Question.set_id == q_set_id).order_by(Question.order)).all()
        snapshot = [{"id": q.id, "text": q.text, "max_duration": q.max_duration} for q in questions]
        interview.session_snapshot = snapshot
        interview.status = "in_progress"
        interview.current_stage = "greeting"
        session.add(interview)
        session.commit()
        session.refresh(interview)
    
    resp = VoiceResponse()
    
    # Step 5: Greeting
    resp.say("お電話ありがとうございます。株式会社パインズのAI面接官です。", language="ja-JP", voice="alice")
    resp.pause(length=1)
    
    # Step 6: Time Check
    gather = Gather(input="speech dtmf", action=f"/voice/time_check?interview_id={interview.id}", timeout=5, language="ja-JP")
    gather.say("只今、面接のお時間はよろしいでしょうか？10分から15分程度となります。はい、か、いいえ、でお答えください。", language="ja-JP", voice="alice")
    resp.append(gather)
    
    # Fallback if no input
    resp.say("聞き取れませんでした。もう一度お願いします。", language="ja-JP", voice="alice")
    resp.redirect(f"/voice/call?interview_id={interview.id}")
    
    return Response(content=str(resp), media_type="application/xml")

@router.post("/time_check")
async def time_check(
    interview_id: int = Query(...),
    SpeechResult: Optional[str] = Form(None),
    Digits: Optional[str] = Form(None),
    session: Session = Depends(get_session)
):
    interview = session.get(Interview, interview_id)
    resp = VoiceResponse()
    
    # Simple Yes/No logic
    positive = ["はい", "yes", "大丈夫", "いいよ", "ok", "ある"]
    negative = ["いいえ", "no", "ない", "だめ", "無理"]
    
    input_val = (SpeechResult or "").lower()
    if Digits == "1": input_val = "yes"
    if Digits == "2": input_val = "no"
    
    is_positive = any(w in input_val for w in positive)
    is_negative = any(w in input_val for w in negative)
    
    if is_negative:
        # Step 7 (Alter): No -> Reschedule
        resp.say("左様でございますか。承知いたしました。", language="ja-JP", voice="alice")
        resp.say("それでは、ご都合の良い日時を教えていただけますでしょうか？お話しいただいた内容は録音され、担当者に伝えられます。お話し終わりましたら、電話をお切りください。", language="ja-JP", voice="alice")
        resp.record(
            action=f"/voice/save_reschedule?interview_id={interview.id}",
            max_length=60,
            timeout=10, # Wait 10s for them to start
            trim="trim-silence"
        )
        # If record finishes, it goes to save_reschedule.
        
    elif is_positive or True: # Default to Yes
        # Step 7: Yes -> Intro
        resp.say("ありがとうございます。それでは、弊社への志望動機など、いくつかご質問をさせていただきます。", language="ja-JP", voice="alice")
        resp.say("各質問の回答時間は最大3分です。回答が終わりましたら、無言でお待ちいただくか、次の質問へとお進みください。", language="ja-JP", voice="alice")
        interview.current_stage = "main_qa"
        session.add(interview)
        session.commit()
        resp.redirect(f"/voice/question?interview_id={interview.id}&q_index=0")
        
    return Response(content=str(resp), media_type="application/xml")

@router.post("/save_reschedule")
async def save_reschedule(
    background_tasks: BackgroundTasks,
    interview_id: int = Query(...),
    RecordingUrl: Optional[str] = Form(None),
    session: Session = Depends(get_session)
):
    interview = session.get(Interview, interview_id)
    if interview:
        interview.status = "reschedule_requested"
        # We store the recording URL in logs or a specific field? 
        # For MVP, let's create a review-like entry or just log.
        # Let's add to communication logs or just print for now as "Note"
        # Ideally, we should add a field to Interview to store "reschedule_recording_url" or create a specialized log.
        # Using CommunicationLog for now using "inbound" type
        from app.models import CommunicationLog
        log = CommunicationLog(
            candidate_id=interview.candidate_id,
            type="voice_reschedule",
            direction="inbound",
            status="received",
            provider_message_id=RecordingUrl, # Storing URL here for convenience
            error_message="User requested reschedule via voice."
        )
        session.add(log)
        session.add(interview)
        session.commit()
        
        # Optionally trigger STT for this too
        # background_tasks.add_task(process_stt_background, ...) # 需要にあれば
        
    resp = VoiceResponse()
    resp.say("ありがとうございます。担当者より改めてご連絡いたします。失礼いたします。", language="ja-JP", voice="alice")
    resp.hangup()
    return Response(content=str(resp), media_type="application/xml")

@router.post("/question")
async def ask_question(
    interview_id: int = Query(...),
    q_index: int = Query(...),
    session: Session = Depends(get_session)
):
    interview = session.get(Interview, interview_id)
    snapshot = interview.session_snapshot
    
    if q_index >= len(snapshot):
        # Done with main questions -> Reverse QA
        resp = VoiceResponse()
        resp.redirect(f"/voice/reverse_qa_intro?interview_id={interview.id}")
        return Response(content=str(resp), media_type="application/xml")
        
    question = snapshot[q_index]
    remaining = len(snapshot) - q_index
    
    resp = VoiceResponse()
    
    # Step 11: Countdown
    if remaining <= 3:
        if remaining == 1:
            resp.say("これが最後の質問です。", language="ja-JP", voice="alice")
        else:
            resp.say(f"残り、{remaining}問です。", language="ja-JP", voice="alice")
            
    # Step 8: Ask
    resp.say(question["text"], language="ja-JP", voice="alice")
    
    # Step 9: Record
    # User wanted "Wait 3 mins", "Trigger 'That's all'".
    # Record allows silence trigger (timeout) or key. capturing speech while recording is tricky.
    # We will encourage Key Press (#).
    # Using trim-silence=true will stop if they stop talking (default 5s silence).
    # Step 9: Record
    # Updated: No "trim-silence" (keep recording even if silent for a bit), 
    # Timeout increased for end detection? Twisted requirement: "wait 3 mins" vs "detect finish".
    # User said: "No silence rule (deprecated)... trigger on 'That's all' OR 3 mins elapsed"
    # Twilio Record cannot trigger on 'That's all'.
    # Compromise: Large timeout (e.g. 10-20s silence) or just max_length.
    # If we remove trim="trim-silence", it records until max_length or hangup or key.
    # But user wants "Trigger next on 'That's all'". We CANNOT do that natively in TwiML <Record>.
    # We would need <Stream> or <Gather input='speech'> (but Gather has limit 60s).
    # Best MVP approach: Use <Record> with keys or long silence.
    # User said "Button setting not instructed". ok.
    # User said "Trigger on 'That's all' OR 3 mins".
    # Since we can't trigger on word in <Record>, we MUST rely on Silence or Time.
    # Current best: Max 180s. Stop on Silence (but user said "Ah/Um might trigger").
    # So we increase silence timeout to say 10-15s?
    
    resp.record(
        action=f"/voice/record?interview_id={interview.id}&q_index={q_index}",
        max_length=180, # 3 mins hard limit
        # finish_on_key="#", # Removed as per "button setting not instructed" (though useful)
        timeout=15, # Wait 15s of silence before assuming done. "Ah..." usually < 5s.
        trim="trim-silence" # If we don't trim, we get 15s of silence at end. fine.
    )
    
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
    if interview:
        snapshot = interview.session_snapshot
        if 0 <= q_index < len(snapshot):
            question = snapshot[q_index]
            review = InterviewReview(
                interview_id=interview.id,
                question_id=question["id"],
                question_text=question["text"],
                recording_url=RecordingUrl,
                duration=int(RecordingDuration) if RecordingDuration else 0
            )
            session.add(review)
            interview.last_completed_q_id = question["id"]
            session.add(interview)
            session.commit()
            
            if RecordingUrl:
                background_tasks.add_task(process_stt_background, review.id, RecordingUrl)
    
    # Step 10: Loop
    resp = VoiceResponse()
    resp.redirect(f"/voice/question?interview_id={interview_id}&q_index={q_index+1}")
    return Response(content=str(resp), media_type="application/xml")

@router.post("/reverse_qa_intro")
async def reverse_qa_intro(interview_id: int = Query(...), session: Session = Depends(get_session)):
    interview = session.get(Interview, interview_id)
    interview.current_stage = "reverse_qa"
    session.add(interview)
    session.commit()
    
    resp = VoiceResponse()
    # Step 12
    resp.say("すべての質問が終わりました。逆に、弊社について聞きたいことはありますか？", language="ja-JP", voice="alice")
    resp.redirect(f"/voice/reverse_qa_listen?interview_id={interview.id}")
    return Response(content=str(resp), media_type="application/xml")

@router.post("/reverse_qa_listen")
async def reverse_qa_listen(interview_id: int = Query(...), first_time: bool = Query(True)):
    resp = VoiceResponse()
    
    if not first_time:
        resp.say("他に何か質問はありますか？なければ、ない、とおっしゃってください。", language="ja-JP", voice="alice")
        
    gather = Gather(input="speech", action=f"/voice/reverse_qa_process?interview_id={interview_id}", language="ja-JP", timeout=3, speechTimeout="auto")
    resp.append(gather)
    
    # If no input, assume no more questions? Or prompt again?
    # Let's prompt once logic
    resp.say("もし質問がなければ、ない、とおっしゃってください。", language="ja-JP", voice="alice")
    resp.redirect(f"/voice/reverse_qa_process?interview_id={interview_id}&no_input=true")
    
    return Response(content=str(resp), media_type="application/xml")

@router.post("/reverse_qa_process")
async def reverse_qa_process(
    interview_id: int = Query(...),
    SpeechResult: Optional[str] = Form(None),
    no_input: bool = Query(False),
    session: Session = Depends(get_session)
):
    interview = session.get(Interview, interview_id)
    resp = VoiceResponse()
    
    text = (SpeechResult or "").strip()
    
    # Step 15: Check exit triggers
    exit_triggers = ["ない", "なし", "大丈夫", "以上", "終わり", "no", "nothing"]
    if no_input or any(t in text.lower() for t in exit_triggers):
        resp.redirect(f"/voice/end?interview_id={interview.id}")
        return Response(content=str(resp), media_type="application/xml")
    
    # Logic: Valid question
    # Step 13: Repeat topic
    topic = extract_topic(text)
    resp.say(f"{topic}についてですね。", language="ja-JP", voice="alice")
    
    # Log it
    logs = list(interview.reverse_qa_logs) if interview.reverse_qa_logs else []
    logs.append({"question": text, "topic": topic, "timestamp": str(datetime.datetime.utcnow())})
    interview.reverse_qa_logs = logs
    session.add(interview)
    session.commit()
    
    # Step 16 (Part of closing info, user said explained here? No, user said "Questions answered for successful candidates only... via email")
    # Actually Step 16 is closing.
    # Here we just acknowledge. "Regarding [Topic], we will answer via email if you pass."
    # Wait, user said "質問内容は合格者のみにお答え... と説明する" at Step 16 (Closing).
    # So here just loop? User said "Repeat back topic... Ask if other questions".
    # User didn't imply answering here.
    
    resp.redirect(f"/voice/reverse_qa_listen?interview_id={interview.id}&first_time=false")
    return Response(content=str(resp), media_type="application/xml")

@router.post("/end")
async def end_call(interview_id: int = Query(...), session: Session = Depends(get_session)):
    interview = session.get(Interview, interview_id)
    interview.status = "completed"
    interview.current_stage = "ending"
    session.add(interview)
    session.commit()
    
    resp = VoiceResponse()
    # Step 16: Closing
    resp.say("ありがとうございます。本日の面接は以上となります。", language="ja-JP", voice="alice")
    resp.say("合否の結果は、7営業日以内に応募サイトよりご連絡いたします。", language="ja-JP", voice="alice")
    resp.say("いただいたご質問については、合格された方にのみ、メール、または次回面接時に回答させていただきます。", language="ja-JP", voice="alice")
    
    # Step 17: Hangup
    resp.say("お忙しい中、お時間をいただきありがとうございました。失礼いたします。", language="ja-JP", voice="alice")
    resp.hangup()
    
    return Response(content=str(resp), media_type="application/xml")

@router.post("/status")
async def call_status(interview_id: int = Query(...), CallStatus: str = Form(...), session: Session = Depends(get_session)):
    interview = session.get(Interview, interview_id)
    if interview:
        print(f"[INFO] Call {interview_id} Status: {CallStatus}")
        # Update connection status logic (omitted for brevity, keep existing retry logic if needed, but user disabled it)
        pass 
    return {"status": "ok"}
