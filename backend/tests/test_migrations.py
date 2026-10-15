import os
import sys
import sqlite3
import subprocess
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

def upgrade(path, revision="head"):
    env = {**os.environ, 'DATABASE_URL': f'sqlite+aiosqlite:///{path}'}
    result = subprocess.run([sys.executable, '-m', 'alembic', '-c', str(BACKEND/'alembic.ini'), 'upgrade', revision], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_fresh_migration_is_repeatable(tmp_path):
    path=tmp_path/'fresh.db'
    upgrade(path); upgrade(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute('SELECT version_num FROM alembic_version').fetchone()[0]=='0002_cleanup_legacy'
        assert conn.execute('SELECT COUNT(*) FROM answer_feedback').fetchone()[0]==0
        assert conn.execute('SELECT COUNT(*) FROM answer_feedback_events').fetchone()[0]==0
        assert conn.execute('SELECT COUNT(*) FROM agent_runs').fetchone()[0]==0



def test_fresh_schema_has_authorization_and_single_active_run(tmp_path):
    path=tmp_path/'constraints.db'
    upgrade(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute('PRAGMA foreign_key_check').fetchall()==[]
        sql=conn.execute("SELECT sql FROM sqlite_master WHERE name='uq_agent_runs_active_conversation'").fetchone()[0]
        assert 'paused' in sql and 'UNIQUE' in sql


def test_fresh_schema_contains_only_current_sql_state(tmp_path):
    path = tmp_path/'sql-only.db'
    upgrade(path)
    with sqlite3.connect(path) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert not {'memory_facts', 'sales_orders'} & tables
        for table in ('conversations', 'business_workspaces', 'question_records', 'messages'):
            columns = {row[1] for row in conn.execute(f'PRAGMA table_info({table})')}
            assert not {'kb_ids', 'citations'} & columns
            if table == 'conversations':
                assert 'source_ids' not in columns


def test_cleanup_exports_legacy_data_and_preserves_paused_run(tmp_path):
    path = tmp_path/'legacy.db'
    upgrade(path, '0001_langgraph')
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE memory_facts (id TEXT PRIMARY KEY, raw_fact TEXT)')
        conn.execute("INSERT INTO memory_facts VALUES ('fact', 'historical fact')")
        conn.execute("INSERT INTO users (id,username,email,hashed_password,created_at,role) VALUES ('user','user',NULL,'unused','2026-10-15','user')")
        conn.execute("INSERT INTO conversations (id,user_id,title,model,scope_version,is_pinned,created_at,updated_at) VALUES ('conversation','user','test','',1,0,'2026-10-15','2026-10-15')")
        conn.execute("INSERT INTO agent_runs (id,user_id,conversation_id,scope_version,resource_scope,input_payload,status,attempts,model,error,created_at) VALUES ('run','user','conversation',1,?, '{}','paused',1,'test','','2026-10-15')",
                     ('{"source_ids":["source"],"kb_ids":[]}',))
    env = {**os.environ, 'DATABASE_URL': f'sqlite+aiosqlite:///{path}', 'STORAGE_DIR': str(tmp_path)}
    result = subprocess.run([sys.executable, '-m', 'alembic', '-c', str(BACKEND/'alembic.ini'), 'upgrade', 'head'], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    import json
    exports = list((tmp_path/'.local-backups/cleanup-legacy').glob('*.json'))
    assert len(exports) == 1
    archive = json.loads(exports[0].read_text())
    assert archive['tables']['memory_facts']['rows'] == [{'id': 'fact', 'raw_fact': 'historical fact'}]
    assert archive['resource_scopes'][0]['resource_scope']['kb_ids'] == []
    assert exports[0].stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(path) as conn:
        scope, status = conn.execute('SELECT resource_scope,status FROM agent_runs').fetchone()
        assert json.loads(scope) == {'source_ids': ['source']}
        assert status == 'paused'
        assert conn.execute('PRAGMA foreign_key_check').fetchall() == []


def test_cleanup_refuses_nonempty_knowledge_scope(tmp_path):
    path = tmp_path/'nonempty.db'
    upgrade(path, '0001_langgraph')
    with sqlite3.connect(path) as conn:
        # Minimal fixture; this connection does not enforce foreign keys.
        conn.execute("INSERT INTO agent_runs (id,user_id,conversation_id,scope_version,resource_scope,input_payload,status,attempts,model,error,created_at) VALUES ('run','user','conversation',1,?, '{}','paused',1,'test','','2026-10-15')",
                     ('{"source_ids":[],"kb_ids":["knowledge"]}',))
    env = {**os.environ, 'DATABASE_URL': f'sqlite+aiosqlite:///{path}', 'STORAGE_DIR': str(tmp_path)}
    result = subprocess.run([sys.executable, '-m', 'alembic', '-c', str(BACKEND/'alembic.ini'), 'upgrade', 'head'], env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert '仍有非空知识库运行范围' in result.stderr
    with sqlite3.connect(path) as conn:
        assert conn.execute('SELECT version_num FROM alembic_version').fetchone()[0] == '0001_langgraph'
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='sales_orders'").fetchone()
