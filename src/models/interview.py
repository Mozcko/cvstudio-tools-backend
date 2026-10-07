import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from src.db.database import Base


class InterviewSession(Base):
    """
    One mock interview: the questions prepared for it, what was said (as text; audio is never
    stored) and the report written at the end. Also what the per-user caps are counted from.
    """

    __tablename__ = "interview_sessions"
    __table_args__ = (Index("ix_interview_sessions_user_created", "user_id", "created_at"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # Short label for the history list, e.g. the job title found in the posting
    title = Column(String, nullable=False, server_default="")
    language = Column(String, nullable=False)
    job_description = Column(Text, nullable=False)
    status = Column(String, nullable=False, server_default="active")  # active | completed
    questions = Column(JSONB, nullable=False)  # [{type, text}]
    turns = Column(JSONB, nullable=False)  # [{role, kind, question, text, at}]
    report = Column(JSONB, nullable=True)
    # Speech generated for this session, to bound its cost
    audio_count = Column(Integer, nullable=False, server_default="0")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
