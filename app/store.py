import sqlite3
from contextlib import contextmanager

from app.config import DATABASE_PATH

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, input_sha256 TEXT NOT NULL, accepted INTEGER NOT NULL, quarantined INTEGER NOT NULL)",
    "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS batches (
        batch_id TEXT PRIMARY KEY,
        input_sha256 TEXT NOT NULL,
        rule_version TEXT NOT NULL,
        created_seq INTEGER NOT NULL,
        accepted INTEGER NOT NULL,
        quarantined INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'ACTIVE',
        created_at TEXT NOT NULL,
        revoked_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS batch_legs (
        leg_id INTEGER PRIMARY KEY AUTOINCREMENT,
        batch_id TEXT NOT NULL,
        business_key TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        line_no INTEGER NOT NULL,
        payload TEXT NOT NULL,
        created_seq INTEGER NOT NULL,
        state TEXT NOT NULL DEFAULT 'ACTIVE',
        UNIQUE(batch_id, business_key)
    )""",
    """CREATE TABLE IF NOT EXISTS batch_evidence (
        evidence_id INTEGER PRIMARY KEY AUTOINCREMENT,
        batch_id TEXT NOT NULL,
        line_no INTEGER NOT NULL,
        reason_code TEXT NOT NULL,
        raw TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS active_legs (
        generation INTEGER NOT NULL,
        business_key TEXT NOT NULL,
        leg_id INTEGER NOT NULL,
        PRIMARY KEY(generation, business_key)
    )""",
    """CREATE TABLE IF NOT EXISTS revocation_previews (
        preview_id TEXT PRIMARY KEY,
        batch_id TEXT NOT NULL,
        import_seq INTEGER NOT NULL,
        base_generation INTEGER NOT NULL,
        dataset_digest TEXT NOT NULL,
        plan TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'VALID',
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS revocation_jobs (
        job_id TEXT PRIMARY KEY,
        batch_id TEXT NOT NULL,
        preview_id TEXT NOT NULL,
        staging_generation INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'RUNNING',
        cursor INTEGER NOT NULL DEFAULT 0,
        checkpoint TEXT NOT NULL DEFAULT '{}',
        report TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS revocation_items (
        job_id TEXT NOT NULL,
        item_index INTEGER NOT NULL,
        business_key TEXT NOT NULL,
        action TEXT NOT NULL,
        state TEXT NOT NULL,
        detail TEXT NOT NULL,
        PRIMARY KEY(job_id, business_key)
    )""",
    """CREATE TABLE IF NOT EXISTS adjudications (
        adjudication_id TEXT PRIMARY KEY,
        batch_id TEXT NOT NULL,
        business_key TEXT NOT NULL,
        preview_id TEXT NOT NULL,
        candidates TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'OPEN',
        resolution TEXT,
        chosen_leg_id INTEGER,
        created_at TEXT NOT NULL,
        resolved_at TEXT,
        UNIQUE(batch_id, business_key)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_batch_legs_key ON batch_legs(business_key)",
    "CREATE INDEX IF NOT EXISTS idx_batch_legs_batch ON batch_legs(batch_id)",
    "CREATE INDEX IF NOT EXISTS idx_active_legs_gen ON active_legs(generation)",
    "CREATE INDEX IF NOT EXISTS idx_previews_batch ON revocation_previews(batch_id)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_batch ON revocation_jobs(batch_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_preview ON revocation_jobs(preview_id)",
    "CREATE INDEX IF NOT EXISTS idx_adjudications_batch ON adjudications(batch_id)",
)

META_DEFAULTS = {
    "dataset_generation": "1",
    "leg_sequence": "0",
    "batch_sequence": "0",
    "import_seq": "0",
}


def connect():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATABASE_PATH, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout = 5000")
    db.execute("PRAGMA foreign_keys = ON")
    return db


@contextmanager
def transaction(db):
    """Explicit transaction so read-modify-write sequences are atomic.

    The connection runs in autocommit mode; this block holds a write lock from
    the first statement, which is what makes the cursor update and item apply
    commit together (resume safety) and the generation switch a single step.
    """
    db.execute("BEGIN IMMEDIATE")
    try:
        yield db
    except BaseException:
        db.execute("ROLLBACK")
        raise
    else:
        db.execute("COMMIT")


def _migrate(db) -> None:
    """Add columns introduced after the first snapshot without a rebuild."""
    additions = {
        "revocation_jobs": {"report": "TEXT"},
        "revocation_items": {"item_index": "INTEGER NOT NULL DEFAULT 0"},
    }
    for table, columns in additions.items():
        existing = {row["name"] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}
        for name, ddl in columns.items():
            if name not in existing:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def init_db():
    db = connect()
    try:
        with transaction(db):
            db.execute("CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, input_sha256 TEXT NOT NULL, accepted INTEGER NOT NULL, quarantined INTEGER NOT NULL)")
            for statement in SCHEMA:
                db.execute(statement)
            _migrate(db)
            for key, value in META_DEFAULTS.items():
                db.execute("INSERT OR IGNORE INTO meta(key, value) VALUES (?, ?)", (key, value))
    finally:
        db.close()


def record_run(manifest: dict) -> bool:
    init_db()
    db = connect()
    try:
        with transaction(db):
            before = db.total_changes
            db.execute("INSERT OR IGNORE INTO runs VALUES (?, ?, ?, ?)", (manifest["run_id"], manifest["input_sha256"], manifest["accepted"], manifest["quarantined"]))
            return db.total_changes > before
    finally:
        db.close()


def run_count() -> int:
    init_db()
    db = connect()
    try:
        return db.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    finally:
        db.close()


def get_meta(db, key: str, default: str | None = None) -> str | None:
    row = db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(db, key: str, value: str) -> None:
    db.execute("INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


def next_meta(db, key: str, start: int = 0) -> int:
    value = int(get_meta(db, key, str(start)) or start) + 1
    set_meta(db, key, str(value))
    return value
