from sqlmodel import Session, select
from app.database import engine
from app.models import Interview, QuestionSet
from dotenv import load_dotenv

load_dotenv()

def check_status():
    with Session(engine) as session:
        # Check Question Set
        qs = session.exec(select(QuestionSet).where(QuestionSet.name == "クリエイター面接")).first()
        if qs:
            print(f"Question Set: {qs.name} (Questions: {len(qs.questions)})")
            for q in qs.questions:
                print(f" - {q.order}. {q.text}")
        
        # Check Last Interview
        interview = session.exec(select(Interview).order_by(Interview.id.desc())).first()
        if interview:
            print(f"Last Interview ID: {interview.id}")
            print(f"Candidate: {interview.candidate.name} ({interview.candidate.phone})")
            print(f"Status: {interview.status}")
            print(f"Time: {interview.reservation_time}")
            
        else:
            print("No interviews found.")

if __name__ == "__main__":
    check_status()
