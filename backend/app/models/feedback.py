"""Immutable answer evidence and append-only human review history."""
from datetime import datetime
import uuid
from sqlalchemy import String, Text, Integer, DateTime, ForeignKey, JSON, UniqueConstraint, CheckConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class AnswerFeedback(Base):
    __tablename__ = 'answer_feedback'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    reporter_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    reporter_name_snapshot: Mapped[str] = mapped_column(String(50))
    assistant_message_key: Mapped[str] = mapped_column(String(36))
    assistant_message_id: Mapped[str | None] = mapped_column(ForeignKey('messages.id', ondelete='SET NULL'))
    question_message_id: Mapped[str | None] = mapped_column(ForeignKey('messages.id', ondelete='SET NULL'))
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey('conversations.id', ondelete='SET NULL'))
    run_id: Mapped[str | None] = mapped_column(ForeignKey('agent_runs.id', ondelete='SET NULL'))
    workspace_id: Mapped[str | None] = mapped_column(String(36))
    question_snapshot: Mapped[str] = mapped_column(Text)
    evidence_snapshot: Mapped[dict] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(String(32))
    user_comment: Mapped[str] = mapped_column(Text, default='')
    status: Mapped[str] = mapped_column(String(20), default='pending')
    processing_note: Mapped[str] = mapped_column(Text, default='')
    last_handled_by: Mapped[str | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'))
    last_handled_at: Mapped[datetime | None] = mapped_column(DateTime)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    __table_args__ = (
        UniqueConstraint('reporter_id', 'assistant_message_key'),
        CheckConstraint("status IN ('pending','resolved')", name='ck_feedback_status'),
        CheckConstraint("reason IN ('data_error','irrelevant','citation_error','presentation_error','other')", name='ck_feedback_reason'),
        CheckConstraint('version >= 1', name='ck_feedback_version'),
        Index('ix_feedback_created', 'created_at', 'id'),
        Index('ix_feedback_status_created', 'status', 'created_at', 'id'),
        Index('ix_feedback_reporter_created', 'reporter_id', 'created_at'),
    )


class AnswerFeedbackEvent(Base):
    __tablename__ = 'answer_feedback_events'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    feedback_id: Mapped[str] = mapped_column(ForeignKey('answer_feedback.id', ondelete='CASCADE'))
    version: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(20))
    actor_id: Mapped[str | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'))
    actor_name_snapshot: Mapped[str] = mapped_column(String(50))
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20))
    old_note: Mapped[str] = mapped_column(Text, default='')
    new_note: Mapped[str] = mapped_column(Text, default='')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint('feedback_id', 'version'),)
