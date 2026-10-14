"""Benchmark feedback list API against a disposable SQLite database, never the application DB."""
import argparse
import asyncio
import json
import os
import secrets
import statistics
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rows', type=int, default=100000)
    parser.add_argument('--samples', type=int, default=20)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.rows < 1 or args.samples < 2:
        parser.error('rows >= 1 and samples >= 2 required')
    with tempfile.TemporaryDirectory(prefix='rag-feedback-bench-') as directory:
        os.environ['DATABASE_URL'] = f'sqlite+aiosqlite:///{directory}/app.db'
        os.environ['STORAGE_DIR'] = directory
        os.environ['SECRET_KEY'] = secrets.token_hex(32)
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        report = asyncio.run(benchmark(args.rows, args.samples))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


async def benchmark(rows, samples):
    import sqlite3
    import httpx
    from sqlalchemy import insert
    from app.database import engine, Base, AsyncSessionLocal
    from app.models.user import User
    from app.models.feedback import AnswerFeedback
    from app.security.auth import create_access_token
    from main import app
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with AsyncSessionLocal() as db:
            user = User(username='benchmark-reviewer', hashed_password='unused', role='feedback_admin')
            db.add(user); await db.flush()
            uid = user.id
            evidence = {'schema_version':1,'answer':{'content':'验收用回答。'*100},'context':{},'resource':{},'execution':{}}
            now = datetime.utcnow()
            for start in range(0, rows, 1000):
                await db.execute(insert(AnswerFeedback), [dict(
                    id=f'{index:036d}', reporter_id=uid, reporter_name_snapshot='benchmark-reviewer',
                    assistant_message_key=f'{index:036d}', question_snapshot=f'本月应收账款账龄核查 {index}',
                    evidence_snapshot=evidence, reason='data_error', status='pending' if index%2 else 'resolved',
                    created_at=now-timedelta(seconds=index), updated_at=now,
                ) for index in range(start, min(rows,start+1000))])
            await db.commit()
        headers={'Authorization':'Bearer '+create_access_token({'sub':uid})}
        results={}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://benchmark',headers=headers) as client:
            cases={'first_page':{},'combined_search':{'question':'账龄','user':'reviewer','status':'pending'},
                   'empty_search':{'question':'不存在的反馈'},'deep_page':{'page':max(1,rows//20),'page_size':10}}
            for name,params in cases.items():
                elapsed=[]
                for trial in range(samples+1):
                    started=time.perf_counter()
                    response=await client.get('/api/feedback',params=params)
                    assert response.status_code==200,response.text
                    duration=(time.perf_counter()-started)*1000
                    if trial: elapsed.append(duration)
                elapsed.sort()
                results[name]={'p50_ms':round(statistics.median(elapsed),2),
                    'p95_ms':round(elapsed[max(0, int(len(elapsed)*0.95+0.999)-1)],2),'max_ms':round(max(elapsed),2)}
        return {'database':'SQLite','sqlite_version':sqlite3.sqlite_version,'rows':rows,'samples_per_case':samples,
                'transport':'ASGI in-process, includes authentication/query/serialization, excludes network',
                'synthetic_data':True,'results':results,'target_p95_ms':500,
                'meets_target':all(value['p95_ms']<500 for value in results.values())}
    finally:
        await engine.dispose()


if __name__=='__main__':
    main()
