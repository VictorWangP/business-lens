"""Grant/revoke feedback review access by UUID. No public role update endpoint."""
import argparse
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.database import AsyncSessionLocal, engine
from app.models.user import User
import app.models


async def run(user_id, revoke):
    try:
        async with AsyncSessionLocal() as db:
            user = await db.get(User, user_id)
            if not user:
                raise SystemExit('用户 UUID 不存在，未修改权限')
            user.role = 'user' if revoke else 'feedback_admin'
            await db.commit()
            print(f'{user.id}: {user.role}')
    finally:
        await engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user-id', required=True)
    parser.add_argument('--revoke', action='store_true')
    args = parser.parse_args()
    asyncio.run(run(args.user_id, args.revoke))
