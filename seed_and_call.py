import os
import datetime
from sqlmodel import Session, select
from app.database import engine, create_db_and_tables
from app.models import QuestionSet, Question, Candidate, Interview
from app.services.notification import make_outbound_call
from dotenv import load_dotenv

# Load envs
load_dotenv()

def setup_and_call():
    # Ensure tables exist
    create_db_and_tables()

    with Session(engine) as session:
        # 1. Create Question Set
        qs_name = "クリエイター面接"
        q_set = session.exec(select(QuestionSet).where(QuestionSet.name == qs_name)).first()
        if not q_set:
            q_set = QuestionSet(name=qs_name, description="デザイナー・クリエイター向け")
            session.add(q_set)
            session.commit()
            session.refresh(q_set)
            print(f"Created QuestionSet: {q_set.name} (ID: {q_set.id})")
        else:
            print(f"Using existing QuestionSet: {q_set.name} (ID: {q_set.id})")

        # 2. Add Questions
        questions_text = [
            "弊社を希望した志望動機を教えてください",
            "Photoshopやillustratorは使用したことがありますか、ある場合はどの程度出来るかを教えてください",
            "AIなどは普段使用していますが、使用している場合はどういったことに使っているかを教えてください"
        ]
        
        # Clear existing questions for this set to avoid duplicates if re-run (optional, but safer for "Register below")
        existing_qs = session.exec(select(Question).where(Question.set_id == q_set.id)).all()
        for eq in existing_qs:
            session.delete(eq)
        session.commit()

        for i, text in enumerate(questions_text):
            q = Question(set_id=q_set.id, text=text, order=i+1, max_duration=60) # 60s for test
            session.add(q)
        session.commit()
        print("Registered 3 questions.")

        # 3. Create Candidate
        phone = "0362409373" # 03-6240-9373
        name = "テスト ユーザー"
        email = "test_call@example.com"
        
        # Check if exists
        candidate = session.exec(select(Candidate).where(Candidate.phone == phone)).first()
        if not candidate:
            import uuid
            token = str(uuid.uuid4())
            candidate = Candidate(name=name, phone=phone, email=email, token=token, question_set_id=q_set.id)
            session.add(candidate)
            session.commit()
            session.refresh(candidate)
            print(f"Created Candidate: {candidate.name} (ID: {candidate.id})")
        else:
            # Update question set
            candidate.question_set_id = q_set.id
            session.add(candidate)
            session.commit()
            session.refresh(candidate)
            print(f"Updated Candidate: {candidate.name} (ID: {candidate.id})")

        # 4. Create Interview (Scheduled NOW)
        reservation_time = datetime.datetime.utcnow()
        interview = Interview(
            candidate_id=candidate.id,
            reservation_time=reservation_time,
            status="scheduled"
        )
        session.add(interview)
        session.commit()
        session.refresh(interview)
        print(f"Created Interview ID: {interview.id} for {reservation_time} UTC")

        # 5. Execute Call
        print(f"Initiating call to {phone}...")
        sid = make_outbound_call(phone, interview.id)
        if sid:
            print(f"Call initiated successfully! SID: {sid}")
            interview.status = "calling"
            session.add(interview)
            session.commit()
        else:
            print("Failed to initiate call. Check Twilio credentials and logs.")

if __name__ == "__main__":
    setup_and_call()
