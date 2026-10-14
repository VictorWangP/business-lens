"""Persistent, user-scoped frequent question groups and processing queue."""
import uuid
from datetime import datetime
from sqlalchemy import String, Text, Integer, DateTime, ForeignKey, JSON, Index, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class QuestionGroup(Base):
    __tablename__ = 'question_groups'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    scope_key: Mapped[str] = mapped_column(String(64), nullable=False)
    representative_question: Mapped[str] = mapped_column(Text, nullable=False)
    representative_asked_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    embedding: Mapped[list] = mapped_column(JSON, nullable=False)
    embedding_profile: Mapped[str] = mapped_column(String(64), nullable=False)
    __table_args__ = (Index('ix_question_groups_user_scope', 'user_id', 'scope_key'),)


class QuestionRecord(Base):
    __tablename__ = 'question_records'
    message_id: Mapped[str] = mapped_column(String(36), ForeignKey('messages.id', ondelete='CASCADE'), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    scope_key: Mapped[str] = mapped_column(String(64), nullable=False)
    kb_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    source_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    group_id: Mapped[str | None] = mapped_column(String(36), ForeignKey('question_groups.id', ondelete='SET NULL'), index=True)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default='pending', nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_code: Mapped[str] = mapped_column(String(80), default='', nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (
        Index('ix_question_records_user_scope_status', 'user_id', 'scope_key', 'status'),
        Index('ix_question_records_status_created', 'status', 'created_at'),
        CheckConstraint("status IN ('pending','processing','completed','skipped','failed')", name='ck_question_record_status'),
    )
