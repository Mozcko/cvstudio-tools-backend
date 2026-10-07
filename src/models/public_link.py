import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import false, func, true

from src.db.database import Base


class PublicLink(Base):
    """A CV published at /u/<slug>. At most one per CV."""

    __tablename__ = "public_links"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cv_id = Column(UUID(as_uuid=True), ForeignKey("cvs.id", ondelete="CASCADE"), nullable=False, unique=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    slug = Column(String, nullable=False, unique=True)
    is_active = Column(Boolean, nullable=False, server_default=true())
    # What of the owner's contact details the public page shows
    show_email = Column(Boolean, nullable=False, server_default=true())
    show_phone = Column(Boolean, nullable=False, server_default=false())
    # Whether search engines may list the page
    indexable = Column(Boolean, nullable=False, server_default=false())
    # When the owner last looked at the statistics; later views are "new"
    views_seen_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class LinkView(Base):
    """One visit to a public link. Holds no IP address: see src/services/public_links.py."""

    __tablename__ = "link_views"
    __table_args__ = (Index("ix_link_views_link_viewed", "link_id", "viewed_at"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    link_id = Column(UUID(as_uuid=True), ForeignKey("public_links.id", ondelete="CASCADE"), nullable=False)
    viewed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # Anonymous, changes every day for the same person
    visitor = Column(String, nullable=False)
    # Only the host of the page the visitor came from, e.g. "linkedin.com"
    referrer_host = Column(String, nullable=True)
