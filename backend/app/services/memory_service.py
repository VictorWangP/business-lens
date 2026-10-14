import json
import re
from typing import List, Dict, Any, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from app.models.memory import UserProfile, MemoryFact

class MemoryService:
    @staticmethod
    async def extract_and_save_memory(
        db: AsyncSession,
        user_id: str,
        conversation_id: str,
        user_query: str,
        ai_response: str
    ):
        """
        轻量异步抽取会话中的用户画像与关键事实并持久化
        """
        # 1. 规则与启发式抽取用户偏好与身份
        profiles_to_add: List[Tuple[str, str, str]] = []  # (category, key, value)
        facts_to_add: List[str] = []

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

        # 2. 事实抽取（如包含具体项目名、公司名、明确指标）
        if "项目" in user_query or "订单" in user_query or "销售" in user_query:
            if len(user_query) > 6:
                facts_to_add.append(f"用户在对话中探讨了业务或项目信息：{user_query[:80]}")

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

        # 写入事实记忆
        for fact_text in facts_to_add:
            new_fact = MemoryFact(
                user_id=user_id,
                raw_fact=fact_text,
                source_conversation_id=conversation_id
            )
            db.add(new_fact)

        try:
            await db.commit()
        except Exception as e:
            await db.rollback()

    @staticmethod
    async def get_user_memory_context(db: AsyncSession, user_id: str, query: str = "", include_facts: bool = True) -> str:
        """
        检索属于该用户的画像和关键事实，组装成系统提示词
        """
        # 1. 查询用户画像
        profile_stmt = select(UserProfile).where(UserProfile.user_id == user_id).limit(10)
        profile_res = await db.execute(profile_stmt)
        profiles = profile_res.scalars().all()

        # 2. 查询关键事实 (最近 5 条)
        fact_stmt = select(MemoryFact).where(MemoryFact.user_id == user_id).order_by(MemoryFact.created_at.desc()).limit(5)
        facts = (await db.scalars(fact_stmt)).all() if include_facts else []

        if not profiles and not facts:
            return ""

        memory_lines = ["\n[长期跨会话记忆 - 用户专属背景]"]
        if profiles:
            memory_lines.append("【用户特征与画像】")
            for p in profiles:
                memory_lines.append(f"- {p.key}: {p.value}")

        if facts:
            memory_lines.append("【历史关键事实与偏好上下文】")
            for f in facts:
                memory_lines.append(f"- {f.raw_fact}")

        memory_lines.append("（请在回答中自然契合用户的画像与偏好，无需生硬告知用户系统调取了记忆。）\n")
        return "\n".join(memory_lines)
