from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class UserProfileOut(BaseModel):
    id: str
    category: str
    key: str
    value: str
    confidence: float
    updated_at: datetime

    class Config:
        from_attributes = True

class MemoryFactOut(BaseModel):
    id: str
    raw_fact: str
    subject: Optional[str] = None
    predicate: Optional[str] = None
    object: Optional[str] = None
    source_conversation_id: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
