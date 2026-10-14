"""Persistent ingestion, retrieval and execution records; owner scope is server supplied."""
import uuid
from datetime import datetime
from sqlalchemy import String, Text, Integer, DateTime, ForeignKey, JSON, UniqueConstraint, Index, text
from sqlalchemy.orm import Mapped, mapped_column
from app.infrastructure.vector_types import vector_type
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

class IngestionJob(Base):
    __tablename__ = 'ingestion_jobs'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey('users.id'), index=True)
    doc_id: Mapped[str] = mapped_column(String(36), ForeignKey('documents.id', ondelete='CASCADE'), index=True)
    version: Mapped[str] = mapped_column(String(36), default=uid)
    batch_id: Mapped[str] = mapped_column(String(36), default='', index=True)
    embedding_config: Mapped[str] = mapped_column(Text, default='')  # encrypted snapshot
    status: Mapped[str] = mapped_column(String(30), default='queued', index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default='')
    content_hash: Mapped[str] = mapped_column(String(64))
    artifact_path: Mapped[str] = mapped_column(Text, default='')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class DocumentChunk(Base):
    __tablename__ = 'document_chunks'
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey('users.id'), index=True)
    kb_id: Mapped[str] = mapped_column(String(36), ForeignKey('knowledge_bases.id', ondelete='CASCADE'), index=True)
    doc_id: Mapped[str] = mapped_column(String(36), ForeignKey('documents.id', ondelete='CASCADE'), index=True)
    version: Mapped[str] = mapped_column(String(36), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSON)
    embedding_profile: Mapped[str] = mapped_column(String(64), index=True)
    embedding: Mapped[list] = mapped_column(vector_type())
    keywords: Mapped[str] = mapped_column(Text, default='')
    __table_args__ = (UniqueConstraint('doc_id', 'version', 'chunk_index'),)

class MaintenanceJob(Base):
    __tablename__ = 'maintenance_jobs'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), default='queued', index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default='')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

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
