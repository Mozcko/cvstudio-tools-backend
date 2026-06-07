from sqlalchemy import Column, String, Integer, Boolean, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid
from src.db.database import Base

class PromoCode(Base):
    __tablename__ = "promo_codes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String, unique=True, index=True, nullable=False)
    max_uses = Column(Integer, default=1)
    used_count = Column(Integer, default=0)
    granted_days = Column(Integer, default=30) # 9999 for lifetime
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
