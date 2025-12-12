import os
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from twilio.rest import Client
from app.models import CommunicationLog
from sqlmodel import Session
from datetime import datetime

# Environment Variables
SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY")
SENDGRID_FROM_EMAIL = os.environ.get("SENDGRID_FROM_EMAIL", "pineseigyousyo@gmail.com")
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_SMS_FROM_NUMBER = os.environ.get("TWILIO_SMS_FROM_NUMBER")

def send_email(to_email: str, subject: str, content: str, candidate_id: int = None, session: Session = None):
    if not SENDGRID_API_KEY:
        print("[WARN] SENDGRID_API_KEY not set. Email skipped.")
        return False

    message = Mail(
        from_email=SENDGRID_FROM_EMAIL,
        to_emails=to_email,
        subject=subject,
        plain_text_content=content)
    
    status = "failed"
    error_msg = None
    provider_id = None
    
    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        if 200 <= response.status_code < 300:
            status = "sent"
            provider_id = response.headers.get("X-Message-Id")
        else:
            error_msg = f"Status Code: {response.status_code}"
    except Exception as e:
        error_msg = str(e)
        print(f"[ERROR] SendGrid Error: {e}")

    if session and candidate_id:
        log = CommunicationLog(
            candidate_id=candidate_id,
            type="email",
            direction="outbound",
            status=status,
            provider_message_id=provider_id,
            error_message=error_msg
        )
        session.add(log)
        session.commit()
    
    return status == "sent"

def send_sms(to_phone: str, content: str, candidate_id: int = None, session: Session = None):
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN or not TWILIO_SMS_FROM_NUMBER:
        print("[WARN] Twilio credentials not set. SMS skipped.")
        return False

    status = "failed"
    error_msg = None
    provider_id = None

    try:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        message = client.messages.create(
            body=content,
            from_=TWILIO_SMS_FROM_NUMBER,
            to=to_phone
        )
        status = "sent" # Strictly "queued" initially
        provider_id = message.sid
    except Exception as e:
        error_msg = str(e)
        print(f"[ERROR] Twilio SMS Error: {e}")

    if session and candidate_id:
        log = CommunicationLog(
            candidate_id=candidate_id,
            type="sms",
            direction="outbound",
            status=status,
            provider_message_id=provider_id,
            error_message=error_msg
        )
        session.add(log)
        session.commit()

    return status == "sent"

def make_outbound_call(to_phone: str, interview_id: int):
    BASE_URL = os.environ.get("BASE_URL")
    if not BASE_URL:
        print("[ERROR] BASE_URL not set. Cannot make call.")
        return None
        
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN or not TWILIO_SMS_FROM_NUMBER:
        pass

    voice_from = os.environ.get("TWILIO_FROM_NUMBER", TWILIO_SMS_FROM_NUMBER)
    
    try:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        
        # Webhook URL for the logic
        url = f"{BASE_URL}/voice/call?interview_id={interview_id}"
        
        call = client.calls.create(
            to=to_phone,
            from_=voice_from,
            url=url,
            status_callback=f"{BASE_URL}/voice/status", 
            status_callback_event=['completed', 'failed', 'busy', 'no-answer'],
            timeout=20 
        )
        return call.sid
    except Exception as e:
        print(f"[ERROR] Twilio Call Error: {e}")
        return None
