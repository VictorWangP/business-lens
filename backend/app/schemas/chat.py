from pydantic import BaseModel, Field
from typing import Optional, Any

class ChatRequest(BaseModel):
    model_config = {"extra": "forbid"}
    conversation_id: Optional[str] = None
    workspace_id: Optional[str] = None
    query: str = Field(min_length=1, max_length=12000)
    model: Optional[str] = None

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
