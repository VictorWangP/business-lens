from pydantic import BaseModel
from datetime import datetime

class UserProfileOut(BaseModel):
    id: str
    category: str
    key: str
    value: str
    confidence: float
    updated_at: datetime

    model_config = {'from_attributes': True}
