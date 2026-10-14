from pydantic import BaseModel
from typing import Optional, List, Any
from datetime import datetime

class ConversationCreate(BaseModel):
    model_config = {"extra": "forbid"}
    title: Optional[str] = "新建对话"
    model: Optional[str] = None
    workspace_id: str
    is_pinned: Optional[bool] = False

class ConversationUpdate(BaseModel):
    model_config = {"extra": "forbid"}
    title: Optional[str] = None
    model: Optional[str] = None
    is_pinned: Optional[bool] = None

class MessageOut(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    tool_calls: Optional[Any] = None
    citations: Optional[Any] = None
    execution_events: Optional[List[Any]] = None
    created_at: datetime

    class Config:
        from_attributes = True

class ConversationOut(BaseModel):
    id: str
    title: str
    model: str
    kb_ids: List[str]
    source_ids: List[str] = []
    workspace_id: Optional[str] = None
    scope_version: int = 0
    is_pinned: bool = False
    created_at: datetime
    updated_at: datetime
    message_count: Optional[int] = 0

    class Config:
        from_attributes = True
