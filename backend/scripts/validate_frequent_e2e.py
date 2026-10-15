"""Real HTTP/SSE + subprocess worker + Aliyun providers, in an isolated temporary database."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--user-id', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    from app.config import settings
    from sqlalchemy.engine import make_url
    source_path = Path(make_url(settings.DATABASE_URL).database).resolve()
    with sqlite3.connect(source_path.as_uri() + '?mode=ro', uri=True) as source:
        row = source.execute("SELECT config_value FROM app_configs WHERE user_id=? AND config_key='model_setting'", (args.user_id,)).fetchone()
    if not row:
        raise ValueError('model_setting_missing')
    model_value = json.loads(row[0])
    selected = {model_value.get('default_model'), model_value.get('default_embedding_model')}
    for item in model_value.get('available_models', []):
        if item['id'] in selected:
            endpoint = urlsplit(item.get('base_url') or '')
            if endpoint.scheme != 'https' or not (endpoint.hostname or '').endswith('.maas.aliyuncs.com'):
                raise ValueError('expected_aliyun_endpoint')
    with tempfile.TemporaryDirectory(prefix='frequent-e2e-') as temp:
        settings.DATABASE_URL = f'sqlite+aiosqlite:///{temp}/app.db'
        settings.STORAGE_DIR = Path(temp) / 'storage'
        settings.OTEL_EXPORTER_OTLP_ENDPOINT = ''
        os.environ.update(DATABASE_URL=settings.DATABASE_URL, STORAGE_DIR=str(settings.STORAGE_DIR), OTEL_EXPORTER_OTLP_ENDPOINT='')
        migration = subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], cwd=BACKEND, capture_output=True)
        if migration.returncode:
            raise RuntimeError('migration_failed')
        return asyncio.run(validate(args, model_value, Path(temp)))

from scripts._chat_validation import chat_input, agent_worker

async def validate(args, model_value, temp):
    import httpx
    from sqlalchemy import select, func
    from app.database import AsyncSessionLocal, engine
    from app.models.user import User
    from app.models.config import AppConfig
    from app.models.conversation import Message
    from app.models.frequent import QuestionRecord, QuestionGroup
    from app.models.platform import DataSource
    from app.security.auth import create_access_token
    from main import app
    report = {'llm_model': model_value['default_model'], 'embedding_model': model_value['default_embedding_model'], 'isolation': 'temporary migrated SQLite database; existing application data unchanged', 'checks': [], 'chats': []}
    worker = None
    worker_log = (temp / 'worker.log').open('w+')

    def save():
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')

    def check(name, condition, evidence=None):
        report['checks'].append({'name': name, 'passed': bool(condition), 'evidence': evidence})
        save()
        print(f"{name}: {('PASS' if condition else 'FAIL')}", flush=True)
        if not condition:
            raise AssertionError(name)

    def start_worker():
        return subprocess.Popen([sys.executable, '-m', 'app.workers.frequent'], cwd=BACKEND, stdout=worker_log, stderr=worker_log)

    def stop_worker():
        nonlocal worker
        if worker:
            worker.terminate()
            try:
                worker.wait(timeout=10)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait(timeout=5)
            worker = None
    try:
        async with AsyncSessionLocal() as db:
            user, other = (User(username='frequent-live-test', hashed_password='unused'), User(username='isolated-user', hashed_password='unused'))
            db.add_all([user, other])
            await db.flush()
            db.add(AppConfig(user_id=user.id, config_key='model_setting', config_value=json.dumps(model_value)))
            db.add(AppConfig(user_id=user.id, config_key='frequent_questions', config_value='{"threshold":3}'))
            ds1 = DataSource(user_id=user.id, name='scope-ds1', connection_secret='unused')
            ds2 = DataSource(user_id=user.id, name='scope-ds2', connection_secret='unused')
            db.add_all([ds1, ds2])
            await db.commit()
            uid, other_id, ds1_id, ds2_id = (user.id, other.id, ds1.id, ds2.id)
        headers = {'Authorization': 'Bearer ' + create_access_token({'sub': uid})}
        other_headers = {'Authorization': 'Bearer ' + create_access_token({'sub': other_id})}
        worker = start_worker()
        async with app.router.lifespan_context(app), agent_worker():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test', timeout=240) as client:
                base_space = await client.post('/api/workspaces', headers=headers, json={'name': '常问验证', 'source_ids': [ds1_id]})
                other_space = await client.post('/api/workspaces', headers=headers, json={'name': '常问范围隔离', 'source_ids': [ds2_id]})
                base_space.raise_for_status()
                other_space.raise_for_status()
                base_wid, scoped_wid = (base_space.json()['id'], other_space.json()['id'])

                async def chat(question, source_ids=None):
                    response = await client.post('/api/chat/stream', headers=headers, json=chat_input(**{'query': question, 'workspace_id': scoped_wid if source_ids else base_wid}))
                    check('chat_http_' + str(len(report['chats']) + 1), response.status_code == 200)
                    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
                    terminal=events[-1] if events else {}
                    done={'conversation_id':terminal.get('threadId'), 'status':'completed' if terminal.get('type')=='RUN_FINISHED' else 'failed'}
                    content = ''.join((event.get('delta', '') for event in events if event['type'] == 'TEXT_MESSAGE_CONTENT'))
                    report['chats'].append({'question': question, 'conversation_id': done.get('conversation_id'), 'status': done.get('status'), 'event_types': sorted(set((e['type'] for e in events))), 'answer_length': len(content)})
                    check('chat_sse_' + str(len(report['chats'])), done.get('status') == 'completed' and bool(content) and (not any((e['type'] == 'RUN_ERROR' for e in events))), {'answer_length': len(content)})
                    async with AsyncSessionLocal() as db:
                        msg = await db.scalar(select(Message).where(Message.conversation_id == done['conversation_id'], Message.role == 'user'))
                        record = await db.get(QuestionRecord, msg.id)
                        return (msg.id, done['conversation_id'], record is not None)

                async def wait_record(mid):
                    deadline = time.monotonic() + 180
                    while time.monotonic() < deadline:
                        if worker.poll() is not None:
                            raise RuntimeError('worker_exited')
                        async with AsyncSessionLocal() as db:
                            record = await db.get(QuestionRecord, mid)
                            if record and record.status in {'completed', 'skipped', 'failed'}:
                                return {'status': record.status, 'attempts': record.attempts, 'group_id': record.group_id, 'error_code': record.error_code}
                        await asyncio.sleep(1)
                    raise TimeoutError('worker_timeout')

                async def listing(params=None, as_other=False):
                    response = await client.get('/api/frequent-questions', params=params if params is not None else {} if as_other else {'workspace_id': base_wid}, headers=other_headers if as_other else headers)
                    if response.status_code != 200:
                        raise RuntimeError('list_api_failed')
                    return response.json()
                questions = ['标准大气压下水的沸点是多少？', '水在一个标准大气压下多少摄氏度会沸腾？', '请问一个标准大气压时，水的沸腾温度是多少摄氏度？']
                mids, conversations = ([], [])
                for index, question in enumerate(questions):
                    mid, conv, enqueued = await chat(question)
                    mids.append(mid)
                    conversations.append(conv)
                    check('message_enqueued_' + str(index + 1), enqueued)
                    record = await wait_record(mid)
                    check('worker_completed_' + str(index + 1), record['status'] == 'completed', record)
                    if index < 2:
                        check('below_threshold_' + str(index + 1), await listing() == [])
                rows = await listing()
                check('three_paraphrases_one_group', len(rows) == 1 and rows[0]['count'] == 3 and (rows[0]['question'] == questions[0]), rows)
                check('cross_user_isolation', await listing(as_other=True) == [])
                check('resource_scope_empty', await listing({'source_ids': 'unavailable-source'}) == [])
                forbidden = await client.post('/api/chat/stream', headers=other_headers, json=chat_input(**{'query': questions[0], 'workspace_id': scoped_wid}))
                check('resource_owner_revalidated', forbidden.status_code == 404)
                mid, conv, _ = await chat(rows[0]['question'])
                mids.append(mid)
                conversations.append(conv)
                check('clicked_question_requery', (await wait_record(mid))['status'] == 'completed' and (await listing())[0]['count'] == 4)
                from app.workers.frequent import process
                await process(mid)
                check('message_idempotent', (await listing())[0]['count'] == 4)
                mid, _, _ = await chat('标准大气压下水的凝固点是多少？')
                different = await wait_record(mid)
                check('different_metric_new_group', different['status'] == 'completed' and different['group_id'] != rows[0]['id'], different)
                mid, _, _ = await chat('你好')
                check('greeting_skipped', (await wait_record(mid))['status'] == 'skipped')
                mid, _, _ = await chat(questions[0], [ds2_id])
                scoped = await wait_record(mid)
                check('resource_group_isolation', scoped['status'] == 'completed' and scoped['group_id'] != rows[0]['id'] and (await listing({'source_ids': ds2_id}) == []), scoped)
                await client.put('/api/settings/app-config/frequent_questions', headers=headers, json={'is_enabled': False})
                mid, _, enqueued = await chat(questions[0])
                check('disabled_no_enqueue', not enqueued and await listing() == [])
                await client.put('/api/settings/app-config/frequent_questions', headers=headers, json={'is_enabled': True})
                check('reenabled_no_backfill', (await listing())[0]['count'] == 4)
                for index, conv in enumerate(conversations[:2]):
                    result = await client.delete('/api/sessions/' + conv, headers=headers)
                    check('delete_conversation_' + str(index + 1), result.status_code == 200)
                    rows_after = await listing()
                    check('delete_reaggregates_' + str(index + 1), rows_after[0]['count'] == 3 if index == 0 else rows_after == [], rows_after)
                stop_worker()
                mid, _, enqueued = await chat(questions[0])
                async with AsyncSessionLocal() as db:
                    record = await db.get(QuestionRecord, mid)
                    record.status = 'processing'
                    record.attempts = 1
                    await db.commit()
                worker = start_worker()
                recovered = await wait_record(mid)
                check('worker_restart_recovers_processing', recovered['status'] == 'completed' and recovered['attempts'] == 2, recovered)
                check('recovered_count', (await listing())[0]['count'] == 3)
                reset = await client.delete('/api/frequent-questions', headers=headers)
                async with AsyncSessionLocal() as db:
                    groups = await db.scalar(select(func.count()).select_from(QuestionGroup))
                    records = await db.scalar(select(func.count()).select_from(QuestionRecord))
                    messages = await db.scalar(select(func.count()).select_from(Message))
                check('reset_preserves_chat', reset.status_code == 200 and groups == 0 and (records == 0) and (messages > 0) and (await listing() == []), {'groups': groups, 'records': records, 'messages': messages})
        report['status'] = 'passed'
    except Exception as exc:
        report['status'] = 'failed'
        report['error_code'] = type(exc).__name__
        print('E2E failed: ' + type(exc).__name__, flush=True)
    finally:
        stop_worker()
        worker_log.close()
        await engine.dispose()
        save()
    return report['status'] == 'passed'
if __name__ == '__main__':
    sys.exit(0 if main() else 1)
