from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

class ChatRequest(BaseModel):
    model_config = {"extra": "forbid"}
    conversation_id: Optional[str] = None
    workspace_id: Optional[str] = None
    query: str = Field(min_length=1, max_length=12000)
    model: Optional[str] = None
    stream: bool = True

class MetricCard(BaseModel):
    label: str
    value: str
    change: Optional[str] = None
    trend: Optional[str] = None  # "up", "down", "neutral"

class ChartConfig(BaseModel):
    type: str  # "bar", "line", "area", "pie"
    title: str
    x_key: str
    y_keys: List[str]
    data: List[Dict[str, Any]]

class CitationItem(BaseModel):
    id: str
    doc_id: str
    doc_name: str
    chunk_index: int
    content: str
    score: Optional[float] = None
    chunk_id: Optional[str] = None
    version: Optional[str] = None
    pages: List[int] = []
    headings: List[str] = []
    retrieval_warning: str = ''

class BookmarkCreate(BaseModel):
    content: str

class BookmarkOut(BaseModel):
    id: str
    content: str
    created_at: Any

class BookmarkToggleOut(BaseModel):
    bookmarked: bool
    content: str
    id: Optional[str] = None
