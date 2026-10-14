"""SQLite FTS5 external-content index maintained in the chunk transaction."""
from sqlalchemy import text


def install(connection):
    connection.execute(text("CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(keywords, content='document_chunks', content_rowid='rowid')"))
    connection.execute(text("""CREATE TRIGGER IF NOT EXISTS chunk_fts_insert AFTER INSERT ON document_chunks BEGIN
        INSERT INTO chunk_fts(rowid, keywords) VALUES (new.rowid, new.keywords); END"""))
    connection.execute(text("""CREATE TRIGGER IF NOT EXISTS chunk_fts_delete AFTER DELETE ON document_chunks BEGIN
        INSERT INTO chunk_fts(chunk_fts, rowid, keywords) VALUES ('delete', old.rowid, old.keywords); END"""))
    connection.execute(text("""CREATE TRIGGER IF NOT EXISTS chunk_fts_update AFTER UPDATE ON document_chunks BEGIN
        INSERT INTO chunk_fts(chunk_fts, rowid, keywords) VALUES ('delete', old.rowid, old.keywords);
        INSERT INTO chunk_fts(rowid, keywords) VALUES (new.rowid, new.keywords); END"""))
    connection.execute(text("INSERT INTO chunk_fts(chunk_fts) VALUES ('rebuild')"))
