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
        assert conn.execute('SELECT version_num FROM alembic_version').fetchone()[0]=='0008_answer_feedback'
        assert conn.execute('SELECT COUNT(*) FROM answer_feedback').fetchone()[0]==0
        assert conn.execute('SELECT COUNT(*) FROM answer_feedback_events').fetchone()[0]==0
        assert conn.execute('SELECT COUNT(*) FROM maintenance_jobs').fetchone()[0]==0
        assert conn.execute('SELECT COUNT(*) FROM agent_runs').fetchone()[0]==0


def test_baseline_preserves_legacy_conversation(tmp_path):
    path=tmp_path/'legacy.db'
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE users (id VARCHAR(36) PRIMARY KEY, username VARCHAR(50), email VARCHAR(100), hashed_password VARCHAR(255), created_at DATETIME)')
        conn.execute('CREATE TABLE conversations (id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(36), title VARCHAR(200), model VARCHAR(50), kb_ids TEXT, created_at DATETIME, updated_at DATETIME)')
        conn.execute("INSERT INTO users VALUES ('u','original',NULL,'hash','2026-01-01')")
        conn.execute("INSERT INTO conversations VALUES ('c','u','真实历史','model','[]','2026-01-01','2026-01-01')")
    upgrade(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute('SELECT title,is_pinned FROM conversations').fetchone()==('真实历史',0)
        assert conn.execute('SELECT kb_ids,source_ids FROM conversations').fetchone()==('[]','[]')
        assert conn.execute('SELECT count(*) FROM conversations c JOIN business_workspaces w ON c.workspace_id=w.id WHERE w.user_id=c.user_id').fetchone()[0] == 1
        assert conn.execute('PRAGMA foreign_key_check').fetchall() == []


def test_workspace_migration_preserves_distinct_legacy_ranges(tmp_path):
    path = tmp_path/'scopes.db'
    upgrade(path, '0005_resource_scope')
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO users (id,username,hashed_password,created_at) VALUES ('u','original','hash','2026-01-01')")
        conn.execute("INSERT INTO business_workspaces (id,user_id,name,kb_ids,source_ids) VALUES ('w','u','销售','[\"kb1\"]','[]')")
        for cid, kbs in [('a','["kb1"]'),('b','["kb2","kb2"]'),('c','["kb2"]'),('d','[]')]:
            conn.execute("INSERT INTO conversations (id,user_id,title,model,kb_ids,source_ids,workspace_id,is_pinned,created_at,updated_at) VALUES (?,'u',?,'model',?,'[]','w',0,'2026-01-01','2026-01-01')",(cid,cid,kbs))
        conn.execute("INSERT INTO messages (id,user_id,conversation_id,role,content,created_at) VALUES ('m','u','b','assistant','旧回答','2026-01-01')")
    upgrade(path); upgrade(path)
    with sqlite3.connect(path) as conn:
        rows = dict(conn.execute('SELECT id,workspace_id FROM conversations'))
        assert rows['a']=='w' and rows['b']==rows['c'] and rows['b']!=rows['d']
        assert conn.execute('SELECT count(*) FROM business_workspaces').fetchone()[0]==3
        assert conn.execute('SELECT content,scope_version FROM messages').fetchone()==('旧回答',0)
        assert conn.execute('PRAGMA foreign_key_check').fetchall()==[]


def test_feedback_migration_upgrade_downgrade_preserves_existing_users(tmp_path):
    path = tmp_path/'feedback.db'
    upgrade(path, '0007_agent_background_runs')
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO users (id,username,hashed_password,created_at) VALUES ('u','original','hash','2026-01-01')")
    upgrade(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute('SELECT username,role FROM users').fetchone()==('original','user')
        assert conn.execute('PRAGMA foreign_key_check').fetchall()==[]
    env = {**os.environ, 'DATABASE_URL':f'sqlite+aiosqlite:///{path}'}
    result = subprocess.run([sys.executable,'-m','alembic','-c',str(BACKEND/'alembic.ini'),'downgrade','0007_agent_background_runs'],env=env,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    with sqlite3.connect(path) as conn:
        assert conn.execute('SELECT username FROM users').fetchone()==('original',)
        assert 'role' not in {row[1] for row in conn.execute('PRAGMA table_info(users)')}
    upgrade(path)
