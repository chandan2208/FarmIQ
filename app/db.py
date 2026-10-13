"""SQLAlchemy engine, session dependency and the community models."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterator

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker

from app.config import settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Post(Base):
    __tablename__ = "posts"
    id = Column(Integer, primary_key=True)
    author = Column(String(60), default="Anonymous", nullable=False)
    title = Column(String(140), nullable=False)
    body = Column(Text, nullable=False)
    topic = Column(String(40), nullable=False, index=True)
    crop = Column(String(40), nullable=True, index=True)
    region = Column(String(80), nullable=True)
    image_path = Column(String(255), nullable=True)
    upvotes = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    comments = relationship("Comment", back_populates="post", cascade="all, delete-orphan", order_by="Comment.created_at")


class Comment(Base):
    __tablename__ = "comments"
    id = Column(Integer, primary_key=True)
    post_id = Column(Integer, ForeignKey("posts.id", ondelete="CASCADE"), nullable=False, index=True)
    author = Column(String(60), default="Anonymous", nullable=False)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    post = relationship("Post", back_populates="comments")


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
