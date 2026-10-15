from typing import List, Dict, Any
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.user import User
from app.models.memory import UserProfile
from app.schemas.memory import UserProfileOut
from app.security.auth import get_current_user

router = APIRouter(prefix="/memory", tags=["用户记忆与画像"])

@router.get("/profiles", response_model=List[UserProfileOut])
async def get_user_profiles(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(UserProfile).where(UserProfile.user_id == current_user.id)
    res = await db.execute(stmt)
    profiles = res.scalars().all()
    return [UserProfileOut.model_validate(p) for p in profiles]
