from datetime import datetime
from typing import Optional, List
from sqlmodel import Field, SQLModel, Relationship, JSON
from sqlalchemy import Column
import uuid

# Models

class QuestionSet(SQLModel, table=True):
    __tablename__ = "question_sets"
    id: int = Field(default=None, primary_key=True)
    name: str  # ex: "営業", "事務"
    description: Optional[str] = None
    
    questions: List["Question"] = Relationship(back_populates="question_set")

class Question(SQLModel, table=True):
    __tablename__ = "questions"
    id: int = Field(default=None, primary_key=True)
    set_id: int = Field(foreign_key="question_sets.id")
    text: str
    order: int
    max_duration: int = Field(default=180)  # seconds
    
    question_set: QuestionSet = Relationship(back_populates="questions")

class Candidate(SQLModel, table=True):
    __tablename__ = "candidates"
    id: int = Field(default=None, primary_key=True)
    name: str
    kana: Optional[str] = None # Furigana
    phone: str
    email: str
    token: str = Field(index=True, unique=True)
    status: str = Field(default="pending") # pending, automated, interviewed, rejected
    created_at: datetime = Field(default_factory=datetime.utcnow)
    token_issued_at: Optional[datetime] = None
    token_sent_type: Optional[str] = None # 'auto', 'manual', 'none'
    question_set_id: Optional[int] = Field(default=None, foreign_key="question_sets.id")
    
    interviews: List["Interview"] = Relationship(back_populates="candidate")
    logs: List["CommunicationLog"] = Relationship(back_populates="candidate")

class Interview(SQLModel, table=True):
    __tablename__ = "interviews"
    id: int = Field(default=None, primary_key=True)
    candidate_id: int = Field(foreign_key="candidates.id")
    reservation_time: datetime
    status: str = Field(default="scheduled") # scheduled, in_progress, completed, failed, interrupted
    session_snapshot: List[dict] = Field(sa_column=Column(JSON)) # snapshot of questions at start
    resume_count: int = Field(default=0)
    retry_count: int = Field(default=0)
    last_completed_q_id: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    # New fields for Logic C Flow
    current_stage: str = Field(default="scheduled") # scheduled, greeting, main_qa, reverse_qa, ending
    reverse_qa_logs: List[dict] = Field(sa_column=Column(JSON), default=[])
    
    candidate: Candidate = Relationship(back_populates="interviews")
    reviews: List["InterviewReview"] = Relationship(back_populates="interview")

class InterviewReview(SQLModel, table=True):
    __tablename__ = "interview_reviews"
    id: int = Field(default=None, primary_key=True)
    interview_id: int = Field(foreign_key="interviews.id")
    question_id: int # ID from Snapshot (not FK to question table to preserve history)
    question_text: str # Text from snapshot
    recording_url: Optional[str] = None
    transcript: Optional[str] = None
    duration: Optional[int] = None
    compliance_flag: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    interview: Interview = Relationship(back_populates="reviews")

class CommunicationLog(SQLModel, table=True):
    __tablename__ = "communication_logs"
    id: int = Field(default=None, primary_key=True)
    candidate_id: Optional[int] = Field(foreign_key="candidates.id", default=None)
    type: str # sms, email
    direction: str # outbound, inbound
    status: str # sent, delivered, failed, received
    provider_message_id: Optional[str] = None
    error_message: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    candidate: Optional[Candidate] = Relationship(back_populates="logs")

class Setting(SQLModel, table=True):
    __tablename__ = "settings"
    key: str = Field(primary_key=True)
    value: str
    description: Optional[str] = None
