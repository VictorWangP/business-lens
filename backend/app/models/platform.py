"""Authorized data sources, metrics and durable SQL Agent execution records."""
import uuid
from datetime import datetime
from sqlalchemy import String, Text, Integer, DateTime, ForeignKey, JSON, UniqueConstraint, Index, text
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

def uid():
    return str(uuid.uuid4())

class DataSource(Base):
    __tablename__ = 'data_sources'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey('users.id'), index=True)
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(30), default='duckdb')
    connection_secret: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default='')
    schema_name: Mapped[str] = mapped_column(String(63), default='main')
    allowed_views: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class MetricDefinition(Base):
    __tablename__ = 'metric_definitions'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey('users.id'), index=True)
    source_id: Mapped[str] = mapped_column(String(36), ForeignKey('data_sources.id', ondelete='CASCADE'), index=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text)
    sql_template: Mapped[str] = mapped_column(Text)
    unit: Mapped[str] = mapped_column(String(30), default='')

class AgentRun(Base):
    __tablename__ = 'agent_runs'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey('users.id'), index=True)
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey('conversations.id', ondelete='CASCADE'), index=True)
    workspace_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    scope_version: Mapped[int] = mapped_column(Integer, default=0)
    resource_scope: Mapped[dict] = mapped_column(JSON, default=dict)
    input_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    assistant_message_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default='queued', index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    model: Mapped[str] = mapped_column(String(100))
    error: Mapped[str] = mapped_column(Text, default='')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    __table_args__ = (Index('uq_agent_runs_active_conversation', 'conversation_id', unique=True,
        sqlite_where=text("status IN ('queued','running','cancel_requested','paused')"),
        postgresql_where=text("status IN ('queued','running','cancel_requested','paused')")),)

class RunEvent(Base):
    __tablename__ = 'run_events'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey('agent_runs.id', ondelete='CASCADE'), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(30))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint('run_id', 'sequence'),)
