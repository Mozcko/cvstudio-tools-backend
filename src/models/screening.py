import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import false, func

from src.db.database import Base


class Screening(Base):
    """One vacancy a recruiter is filling: the job description, the rubric derived from it, and
    the candidates evaluated against it. Deleted on its own when `expires_at` passes."""

    __tablename__ = "screenings"
    __table_args__ = (Index("ix_screenings_user_created", "user_id", "created_at"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String, nullable=False)
    job_description = Column(Text, nullable=False)
    language = Column(String, nullable=False)
    # [{id, text, kind: "must" | "nice"}]: what every candidate is judged against
    rubric = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)


class ScreeningCandidate(Base):
    """A candidate's CV in a screening. This is other people's personal data: it lives only as
    long as its screening does."""

    __tablename__ = "screening_candidates"
    __table_args__ = (
        UniqueConstraint("screening_id", "text_hash", name="uq_screening_candidates_text"),
        Index("ix_screening_candidates_screening", "screening_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    screening_id = Column(UUID(as_uuid=True), ForeignKey("screenings.id", ondelete="CASCADE"), nullable=False)
    # Shown to the recruiter; never sent to the AI
    display_name = Column(String, nullable=False)
    file_name = Column(String, nullable=False, server_default="")
    contact = Column(JSONB, nullable=False)  # {emails, phones, links}
    text_hash = Column(String, nullable=False)
    score = Column(Integer, nullable=False)  # 0-100, computed here from the rubric
    missing_musts = Column(Integer, nullable=False, server_default="0")
    # The CV contains text that reads like instructions to an AI
    flagged = Column(Boolean, nullable=False, server_default=false())
    result = Column(JSONB, nullable=False)  # {requirements, strengths, concerns, summary}
    note = Column(Text, nullable=False, server_default="")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
