from typing import List, Dict, Any
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.user import User
from app.models.memory import UserProfile, MemoryFact
from app.schemas.memory import UserProfileOut, MemoryFactOut
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

@router.get("/facts", response_model=List[MemoryFactOut])
async def get_memory_facts(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(MemoryFact).where(
        MemoryFact.user_id == current_user.id
    ).order_by(MemoryFact.created_at.desc()).limit(20)
    res = await db.execute(stmt)
    facts = res.scalars().all()
    return [MemoryFactOut.model_validate(f) for f in facts]
