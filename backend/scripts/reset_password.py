"""Reset user password in application SQLite database."""
import argparse
import asyncio
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))

from app.database import AsyncSessionLocal, engine
from app.models.user import User
from app.security.auth import get_password_hash
from sqlalchemy import select


async def reset(username: str, new_password: str):
    try:
        async with AsyncSessionLocal() as db:
            stmt = select(User).where(User.username == username)
            res = await db.execute(stmt)
            user = res.scalar_one_or_none()
            if not user:
                raise SystemExit(f"用户 '{username}' 不存在")
            user.hashed_password = get_password_hash(new_password)
            await db.commit()
            print(f"用户 '{username}' 密码已重置为: {new_password}")
    finally:
        await engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--username', default='admin')
    parser.add_argument('--password', default='admin123')
    args = parser.parse_args()
    asyncio.run(reset(args.username, args.password))
