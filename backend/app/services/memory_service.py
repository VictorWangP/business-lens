import re
from typing import List, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from app.models.memory import UserProfile

class MemoryService:
    @staticmethod
    async def save_preferences(db: AsyncSession, user_id: str, user_query: str):
        """Persist user preferences only; business facts stay in scoped SQL evidence."""
        # 1. 规则与启发式抽取用户偏好与身份
        profiles_to_add: List[Tuple[str, str, str]] = []  # (category, key, value)

        query_lower = user_query.lower()
        if any(w in query_lower for w in ["我是", "我做", "我的职业", "我的岗位"]):
            match = re.search(r"(?:我是|我是个|我做|我的岗位是)([^，。！？\n]+)", user_query)
            if match:
                role = match.group(1).strip()
                profiles_to_add.append(("role", "职业与身份", role))

        if any(w in query_lower for w in ["喜欢", "偏好", "倾向于", "请用", "请画"]):
            if "图表" in query_lower or "柱状图" in query_lower or "折线图" in query_lower:
                profiles_to_add.append(("preference", "展示偏好", "偏好数据可视化图表展示"))
            if "简短" in query_lower or "精炼" in query_lower:
                profiles_to_add.append(("preference", "回答风格", "偏好简明扼要的回答风格"))

        # 写入画像 (去重更新)
        for cat, k, v in profiles_to_add:
            stmt = select(UserProfile).where(
                and_(
                    UserProfile.user_id == user_id,
                    UserProfile.key == k
                )
            )
            res = await db.execute(stmt)
            existing = res.scalar_one_or_none()
            if existing:
                existing.value = v
            else:
                new_profile = UserProfile(
                    user_id=user_id,
                    category=cat,
                    key=k,
                    value=v,
                    confidence=0.9
                )
                db.add(new_profile)

        try:
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    @staticmethod
    async def get_user_memory_context(db: AsyncSession, user_id: str) -> str:
        profiles = (await db.scalars(select(UserProfile).where(UserProfile.user_id == user_id)
            .order_by(UserProfile.key, UserProfile.id).limit(10))).all()
        if not profiles:
            return ''
        return '【用户偏好，不是业务事实】\n' + '\n'.join(f'- {p.key}: {p.value}' for p in profiles)
