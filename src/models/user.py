from sqlalchemy import Boolean, Column, DateTime, String
from sqlalchemy.sql import func

from src.db.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, index=True)  # This will be the Clerk User ID
    email = Column(String, unique=True, index=True, nullable=True)
    is_pro = Column(Boolean, default=False)
    pro_expires_at = Column(DateTime(timezone=True), nullable=True)
    # End of the premium level (Active Hunt). Always within the Pro period; lifetime users
    # are premium without it. See src/services/pro.py
    premium_until = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
