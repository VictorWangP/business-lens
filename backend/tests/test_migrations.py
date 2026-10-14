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
        assert conn.execute('SELECT version_num FROM alembic_version').fetchone()[0]=='0001_langgraph'
        assert conn.execute('SELECT COUNT(*) FROM answer_feedback').fetchone()[0]==0
        assert conn.execute('SELECT COUNT(*) FROM answer_feedback_events').fetchone()[0]==0
        assert conn.execute('SELECT COUNT(*) FROM maintenance_jobs').fetchone()[0]==0
        assert conn.execute('SELECT COUNT(*) FROM agent_runs').fetchone()[0]==0



def test_fresh_schema_has_authorization_and_single_active_run(tmp_path):
    path=tmp_path/'constraints.db'
    upgrade(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute('PRAGMA foreign_key_check').fetchall()==[]
        sql=conn.execute("SELECT sql FROM sqlite_master WHERE name='uq_agent_runs_active_conversation'").fetchone()[0]
        assert 'paused' in sql and 'UNIQUE' in sql
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='chunk_fts'").fetchone()
