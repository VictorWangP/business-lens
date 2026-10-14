from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class KnowledgeBaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default='', max_length=4000)

class RetrievalProbe(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=6, ge=1, le=12)
    mode: str = Field(default='hybrid', pattern='^(hybrid|keyword|vector)$')
    min_similarity: float = Field(default=0.25, ge=-1, le=1)

class KnowledgeBaseOut(BaseModel):
    id: str
    name: str
    description: str
    document_count: Optional[int] = 0
    created_at: datetime
    index_batch_id: str = ''

    class Config:
        from_attributes = True

class DocumentOut(BaseModel):
    id: str
    kb_id: str
    filename: str
    file_size: int
    status: str  # queued, parsing, indexing, ready, failed
    progress: float
    error_msg: str
    chunk_count: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
