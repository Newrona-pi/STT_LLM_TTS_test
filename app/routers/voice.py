
import os
import json
import asyncio
import websockets
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request, Query, Depends, Form, BackgroundTasks
from fastapi.responses import Response
from sqlmodel import Session, select
from twilio.twiml.voice_response import VoiceResponse, Connect
from twilio.rest import Client
from app.database import get_session
from app.models import Interview, QuestionSet, Question, InterviewReview, CommunicationLog, Candidate
import datetime

# Configuration
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
BASE_URL = os.environ.get("BASE_URL", "").replace("https://", "").replace("http://", "").rstrip('/')

router = APIRouter(prefix="/voice", tags=["voice"])

async def start_twilio_recording(call_sid: str):
    """Starts a dual-channel recording of the call."""
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
        print("[WARN] Twilio Credentials missing for recording.")
        return
    # Wait a bit to ensure call is established
    await asyncio.sleep(1)
    try:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        # Using 'dual' to record speaker and listener separately
        client.calls(call_sid).recordings.create(recording_channels='dual')
        print(f"[INFO] Started Twilio recording for {call_sid}")
    except Exception as e:
        print(f"[WARN] Failed to start recording: {e}")

@router.post("/call")
async def start_call(
    background_tasks: BackgroundTasks,
    interview_id: int = Query(...),
    CallSid: str = Form(None), # Twilio sends CallSid
    session: Session = Depends(get_session)
):
    interview = session.get(Interview, interview_id)
    if not interview:
        resp = VoiceResponse()
        resp.say("エラー。面接情報が見つかりません。", language="ja-JP")
        return Response(content=str(resp), media_type="application/xml")

    # Ensure Session Snapshot
    if not interview.session_snapshot:
        questions = []
        if interview.candidate and interview.candidate.question_set_id:
            questions = session.exec(select(Question).where(Question.set_id == interview.candidate.question_set_id).order_by(Question.order)).all()
        else:
            # Fallback
            qs = session.exec(select(QuestionSet)).first()
            if qs: 
                questions = session.exec(select(Question).where(Question.set_id == qs.id).order_by(Question.order)).all()
        
        interview.session_snapshot = [{"id": q.id, "text": q.text, "max_duration": q.max_duration} for q in questions]
        interview.status = "in_progress"
        interview.current_stage = "intro"
        session.add(interview)
        session.commit()
    
    # NOTE: Recording is now started inside WebSocket 'start' event to avoid 400 race conditions.

    resp = VoiceResponse()
    resp.pause(length=1)
    connect = Connect()
    # Construct WSS URL
    # Using query param for interview_id
    wss_url = f"wss://{BASE_URL}/voice/stream?interview_id={interview.id}"
    connect.stream(url=wss_url)
    resp.append(connect)
    
    return Response(content=str(resp), media_type="application/xml")

@router.post("/status")
async def call_status(CallSid: str = Form(None), CallStatus: str = Form(None)):
    """Callback for Call Status updates (prevents 404)."""
    if CallStatus:
        print(f"[INFO] Call {CallSid} Status: {CallStatus}")
    return Response(status_code=200)

@router.websocket("/stream")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for Twilio Media Stream <-> OpenAI Realtime API.
    Manually parses interview_id to avoid 403 Forbidden from dependency validation.
    """
    await websocket.accept()
    
    # 1. Parse interview_id safely
    try:
        interview_id_str = websocket.query_params.get("interview_id")
        if not interview_id_str:
            print("[WARN] WebSocket missing interview_id")
            await websocket.close()
            return
        interview_id = int(interview_id_str)
    except Exception as e:
        print(f"[WARN] Invalid interview_id: {e}")
        await websocket.close()
        return

    from app.database import engine
    # Use a fresh session for this connection
    with Session(engine) as session:
        interview = session.get(Interview, interview_id)
        if not interview:
            print(f"[WARN] Interview {interview_id} not found")
            await websocket.close()
            return
        
        print(f"[INFO] WebSocket Start. Interview ID: {interview_id}")

        # --- State Variables ---
        state = {
            "stage": "intro", # intro, time_check, main_qa, reverse_qa, ending
            "q_index": 0,
            "questions": interview.session_snapshot or [],
            "stream_sid": None,
            "current_transcript": [] # Accumulate user speech per turn
        }

        # --- Helper: Save Q&A Log ---
        def save_qa_log(q_text, a_text):
            # Find question ID if possible
            q_id = None
            if state["q_index"] < len(state["questions"]):
                 if state["questions"][state["q_index"]]["text"] == q_text:
                     q_id = state["questions"][state["q_index"]]["id"]
            
            # 1. Text Correction (Simple Rule-based)
            corrected_text = a_text.replace("死亡動機", "志望動機")
            
            # 2. Compliance Check
            is_compliant_issue = False
            blocklist = ["死ね", "馬鹿", "暴力", "脅迫", "差別"] # Extend as needed
            for w in blocklist:
                if w in corrected_text:
                    is_compliant_issue = True
                    break
            
            review = InterviewReview(
                interview_id=interview.id,
                question_id=q_id,
                question_text=q_text,
                transcript=corrected_text, 
                recording_url="[Full Call Recording]", # Placeholder
                duration=0,
                compliance_flag=is_compliant_issue
            )
            session.add(review)
            session.commit()
            print(f"[LOG] Saved Review: {q_text} -> {corrected_text} (Compliant: {not is_compliant_issue})")

        # --- OpenAI Connection ---
        # User requested strict usage of 'gpt-realtime'
        openai_url = "wss://api.openai.com/v1/realtime?model=gpt-realtime"
        
        # [Evidence A] Log the connection URL
        print(f"[INFO] Connecting to OpenAI Realtime API. URL: {openai_url}")
        
        openai_headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "OpenAI-Beta": "realtime=v1"
        }
        
        async with websockets.connect(openai_url, extra_headers=openai_headers) as openai_ws:
            
            # 1. Initialize Session
            session_config = {
                "type": "session.update",
                "session": {
                    "modalities": ["text", "audio"],
                    "instructions": """
                    あなたは株式会社パインズのAI面接官です。
                    ユーザーの回答を遮らないでください。
                    相槌は適度に入れてください。
                    """,
                    "voice": "shimmer",
                    "input_audio_format": "g711_ulaw",
                    "output_audio_format": "g711_ulaw",
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": 0.5,
                        "prefix_padding_ms": 300,
                        "silence_duration_ms": 2000 
                    }
                }
            }
            await openai_ws.send(json.dumps(session_config))
            
            # --- Event Loops ---
            async def twilio_receiver():
                try:
                    async for message in websocket.iter_text():
                        data = json.loads(message)
                        if data['event'] == 'media':
                            await openai_ws.send(json.dumps({
                                "type": "input_audio_buffer.append",
                                "audio": data['media']['payload']
                            }))
                        elif data['event'] == 'start':
                            state["stream_sid"] = data['start']['streamSid']
                            call_sid = data['start'].get('callSid')
                            
                            print(f"[INFO] Stream started: {state['stream_sid']} (Call: {call_sid})")

                            # Start Recording Here (Call is active)
                            if call_sid:
                                asyncio.create_task(start_twilio_recording(call_sid))

                            # Start Intro - Strict Instructions
                            await openai_ws.send(json.dumps({
                                "type": "response.create",
                                "response": {
                                    "instructions": """
                                    次のセリフを正確に読み上げてください：
                                    「お忙しいところ、お時間をいただき、ありがとうございます。株式会社パインズのAI面接官です。
                                    只今、面接のお時間はよろしいでしょうか？10分から15分程度となります。はい、か、いいえ、でお答えください。
                                    お話しいただいた内容は録音され、担当者に伝えられます。
                                    ありがとうございます。それでは、弊社への志望動機など、いくつかご質問をさせていただきます。」
                                    """
                                }
                            }))
                except WebSocketDisconnect:
                    print("[INFO] Twilio Disconnected")
                except Exception as e:
                    print(f"[ERROR] Twilio Receiver: {e}")

            async def openai_receiver():
                try:
                    async for message in openai_ws:
                        data = json.loads(message)
                        evt = data.get("type")
                        
                        if evt in ["session.created", "session.updated"]:
                             print(f"[INFO] OpenAI Session Event ({evt}): {json.dumps(data)}")

                        if evt == "response.audio.delta":
                            if state["stream_sid"]:
                                await websocket.send_text(json.dumps({
                                    "event": "media",
                                    "streamSid": state["stream_sid"],
                                    "media": {"payload": data["delta"]}
                                }))
                                
                        elif evt == "conversation.item.input_audio_transcription.completed":
                            # User text segment
                            text = data.get("transcript", "")
                            if text:
                                state["current_transcript"].append(text)
                                print(f"[User]: {text}")
                            
                                # Concatenate for logic check
                                full_text = " ".join(state["current_transcript"])
                                
                                # Logic Transition
                                transition_happened = False
                                
                                if state["stage"] == "intro":
                                    if "はい" in full_text or "大丈夫" in full_text:
                                        state["stage"] = "main_qa"
                                        state["current_transcript"] = [] # Reset buffer
                                        q_text = state["questions"][0]["text"]
                                        await openai_ws.send(json.dumps({
                                            "type": "response.create",
                                            "response": {
                                                "instructions": f"「ありがとうございます。」と言い、次の質問をしてください：「質問1：{q_text}」"
                                            }
                                        }))
                                        transition_happened = True
                                    elif "いいえ" in full_text:
                                        state["stage"] = "ending"
                                        await openai_ws.send(json.dumps({
                                            "type": "response.create",
                                            "response": {"instructions": "謝罪し、都合の良い日時を聞いてください。"}
                                        }))
                                        transition_happened = True

                                elif state["stage"] == "main_qa":
                                    if "以上です" in full_text or "終わり" in full_text:
                                        # Save LOG for current question
                                        current_q = state["questions"][state["q_index"]]["text"]
                                        save_qa_log(current_q, full_text)
                                        
                                        # Proceed
                                        state["q_index"] += 1
                                        state["current_transcript"] = []
                                        
                                        if state["q_index"] < len(state["questions"]):
                                            q_text = state["questions"][state["q_index"]]["text"]
                                            await openai_ws.send(json.dumps({
                                                "type": "response.create",
                                                "response": {"instructions": f"「ありがとうございます。」と言い、次の質問：{q_text}"}
                                            }))
                                        else:
                                            state["stage"] = "reverse_qa"
                                            await openai_ws.send(json.dumps({
                                                "type": "response.create",
                                                "response": {"instructions": "「すべての質問が終わりました。逆に、弊社について聞きたいことはありますか？」"}
                                            }))
                                        transition_happened = True

                                elif state["stage"] == "reverse_qa":
                                    if "ない" in full_text:
                                        state["stage"] = "ending"
                                        await openai_ws.send(json.dumps({
                                            "type": "response.create",
                                            "response": {"instructions": "「本日の面接は以上となります。合否の結果は、7営業日以内に応募サイトよりご連絡いたします。お忙しい中、お時間をいただきありがとうございました。失礼いたします。」"}
                                        }))
                                    else:
                                        # Log Reverse QA
                                        save_qa_log("逆質問", full_text)
                                        
                                        # Repeat topic
                                        state["current_transcript"] = [] 
                                        await openai_ws.send(json.dumps({
                                            "type": "response.create",
                                            "response": {"instructions": "「その点については、合格された場合にお答えします。他に質問はありますか？」"}
                                        }))

                except Exception as e:
                    print(f"[ERROR] OpenAI WS: {e}")

            await asyncio.gather(twilio_receiver(), openai_receiver())
