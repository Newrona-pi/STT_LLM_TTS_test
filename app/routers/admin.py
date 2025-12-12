from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlmodel import Session, select
from app.database import get_session
from app.models import Candidate, QuestionSet, Question, Interview
import secrets
import csv
import codecs
import uuid

router = APIRouter(prefix="/admin", tags=["admin"])
security = HTTPBasic()

def get_current_username(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = secrets.compare_digest(credentials.username, "admin")
    correct_password = secrets.compare_digest(credentials.password, "pines")
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

# --- Question Sets ---

@router.post("/question-sets")
def create_question_set(name: str, description: str = None, session: Session = Depends(get_session), username: str = Depends(get_current_username)):
    q_set = QuestionSet(name=name, description=description)
    session.add(q_set)
    session.commit()
    session.refresh(q_set)
    return q_set

@router.get("/question-sets")
def list_question_sets(session: Session = Depends(get_session), username: str = Depends(get_current_username)):
    return session.exec(select(QuestionSet)).all()

@router.post("/question-sets/{set_id}/questions")
def add_question(set_id: int, text: str, order: int, max_duration: int = 180, session: Session = Depends(get_session), username: str = Depends(get_current_username)):
    q_set = session.get(QuestionSet, set_id)
    if not q_set:
        raise HTTPException(status_code=404, detail="Question Set not found")
    
    question = Question(set_id=set_id, text=text, order=order, max_duration=max_duration)
    session.add(question)
    session.commit()
    session.refresh(question)
    return question

@router.get("/question-sets/{set_id}/questions")
def list_questions(set_id: int, session: Session = Depends(get_session), username: str = Depends(get_current_username)):
    return session.exec(select(Question).where(Question.set_id == set_id).order_by(Question.order)).all()


# --- Candidates ---

@router.post("/candidates/upload")
async def upload_candidates(file: UploadFile = File(...), session: Session = Depends(get_session), username: str = Depends(get_current_username)):
    # CSV format: name, phone, email
    candidates_created = []
    
    try:
        content = await file.read()
        # Decode considering BOM for Excel
        if content.startswith(codecs.BOM_UTF8):
            decoded = content.decode("utf-8-sig")
        else:
            try:
                decoded = content.decode("utf-8")
            except UnicodeDecodeError:
                decoded = content.decode("shift_jis") # Fallback for Japanese Excel
                
        reader = csv.reader(decoded.splitlines())
        header = next(reader, None) # Skip header if assumed
        
        for row in reader:
            if len(row) < 3:
                continue
            name, phone, email = row[0], row[1], row[2]
            
            # Optional question set
            q_set_id = None
            if len(row) >= 4 and row[3].strip():
                qs_name = row[3].strip()
                q_set = session.exec(select(QuestionSet).where(QuestionSet.name == qs_name)).first()
                if q_set:
                    q_set_id = q_set.id
                else:
                    # Optional: Create if not exists or ignore? Requirement says "manage question sets" separately.
                    # Let's ignore or log warning if not found, to imply strict management.
                    # Or maybe create a default? Let's leave as None if not found for MVP.
                    print(f"[WARN] Question Set '{qs_name}' not found for candidate {name}")

            # Create unique token
            token = str(uuid.uuid4())
            
            candidate = Candidate(name=name, phone=phone, email=email, token=token, question_set_id=q_set_id)
            session.add(candidate)
            candidates_created.append(candidate)
            
        session.commit()
        for c in candidates_created:
            session.refresh(c)
            
        return {"message": f"Created {len(candidates_created)} candidates", "candidates": candidates_created}
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/candidates")
def list_candidates(session: Session = Depends(get_session), username: str = Depends(get_current_username)):
    return session.exec(select(Candidate)).all()

# --- Interviews ---
@router.get("/interviews")
def list_interviews(session: Session = Depends(get_session), username: str = Depends(get_current_username)):
    return session.exec(select(Interview)).all()
