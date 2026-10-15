from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, Any
from datetime import datetime
from app.agents.answer import BusinessPresentation

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

class MessageMetadata(BaseModel):
    model_config = ConfigDict(extra='ignore')
    presentation: BusinessPresentation | None = None
    run_id: str | None = None
    status: str | None = None
    last_sequence: int | None = None
    interrupts: list[dict] = Field(default_factory=list)
    execution_events: list[dict] = Field(default_factory=list)


class MessageOut(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    tool_calls: Optional[Any] = None
    created_at: datetime

    model_config = {'from_attributes': True}

class ConversationOut(BaseModel):
    id: str
    title: str
    model: str
    workspace_id: Optional[str] = None
    scope_version: int = 0
    is_pinned: bool = False
    created_at: datetime
    updated_at: datetime
    message_count: Optional[int] = 0

    model_config = {'from_attributes': True}
