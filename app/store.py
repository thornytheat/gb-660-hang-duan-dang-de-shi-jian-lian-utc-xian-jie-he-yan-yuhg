import sqlite3
from app.config import DATABASE_PATH

def connect():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DATABASE_PATH)

def init_db():
    with connect() as db:
        db.execute("CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, input_sha256 TEXT NOT NULL, accepted INTEGER NOT NULL, quarantined INTEGER NOT NULL)")

def record_run(manifest: dict) -> bool:
    init_db()
    with connect() as db:
        before = db.total_changes
        db.execute("INSERT OR IGNORE INTO runs VALUES (?, ?, ?, ?)", (manifest["run_id"], manifest["input_sha256"], manifest["accepted"], manifest["quarantined"]))
        return db.total_changes > before

def run_count() -> int:
    init_db()
    with connect() as db:
        return db.execute("SELECT COUNT(*) FROM runs").fetchone()[0]

