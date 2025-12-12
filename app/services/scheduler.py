from apscheduler.schedulers.background import BackgroundScheduler
from sqlmodel import Session, select
from app.database import engine
from app.models import Interview
from app.services.notification import make_outbound_call
from datetime import datetime, timedelta
import pytz

# Initialize Scheduler
scheduler = BackgroundScheduler()

def check_scheduled_interviews():
    """
    Check for interviews scheduled now (or in past) that are still 'scheduled'.
    Make calls.
    """
    with Session(engine) as session:
        now = datetime.now(pytz.utc) # DB stores UTC usually, or naive. SQLModel default is naive UTC often.
        # Let's assume naive UTC in DB.
        
        # interviews = session.exec(select(Interview).where(Interview.status == "scheduled", Interview.reservation_time <= now)).all()
        # Comparison depends on how reservation_time is stored. If naive, assume UTC.
        # Implementation Plan says Asia/Tokyo fixed. But datetime.utcnow() is UTC.
        # If user inputs JST date in booking, we should convert to UTC before saving or save as naive JST?
        # Standard: Save as UTC.
        # Let's ensure booking saves as UTC.
        
        # For query:
        interviews = session.exec(select(Interview).where(Interview.status == "scheduled")).all()
        
        for interview in interviews:
            # Check time
            # Assume reservation_time is naive UTC
            if interview.reservation_time <= datetime.utcnow():
                print(f"[INFO] Triggering call for Interview {interview.id}")
                
                # Make Call
                call_sid = make_outbound_call(interview.candidate.phone, interview.id)
                
                if call_sid:
                    interview.status = "calling" # Temporary status to prevent double-dialing
                    session.add(interview)
                    session.commit()
                else:
                    print(f"[ERROR] Failed to initiate call for Interview {interview.id}. Will retry next loop enabled by not changing status? Or retry count?")
                    # If make_call fails (e.g. auth error), we might want to fail hard or retry
                    # For now keep 'scheduled' so it retries, but might loop if config error.
                    # Add simple error counter? Or rely on retry logic via status check.
                    pass

def start_scheduler():
    scheduler.add_job(check_scheduled_interviews, 'interval', seconds=60)
    scheduler.start()
    print("[INFO] Scheduler started.")
