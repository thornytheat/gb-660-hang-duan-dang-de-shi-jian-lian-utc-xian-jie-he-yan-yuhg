"""Persistent leg ledger with per-batch provenance.

Every accepted leg version is stored against the batch that imported it.  The
materialised dataset is an append-only sequence of *generations*: a generation
is only readable once it becomes the current dataset generation, which lets a
revocation build a replacement generation while the old chain stays readable.
"""

import hashlib
import json
from datetime import datetime, timezone

from app.config import RULE_VERSION
from app.store import connect, get_meta, init_db, next_meta, set_meta


def canonical(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def content_hash(payload: dict) -> str:
    return hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def dataset_digest(db, generation: int | None = None) -> str:
    generation = generation if generation is not None else current_generation(db)
    rows = db.execute(
        "SELECT al.business_key, bl.content_hash FROM active_legs al JOIN batch_legs bl ON bl.leg_id = al.leg_id "
        "WHERE al.generation = ? ORDER BY al.business_key",
        (generation,),
    ).fetchall()
    return hashlib.sha256("\n".join(f"{row['business_key']}={row['content_hash']}" for row in rows).encode()).hexdigest()


def current_generation(db) -> int:
    return int(get_meta(db, "dataset_generation", "1") or 1)


def import_sequence(db) -> int:
    return int(get_meta(db, "import_seq", "0") or 0)


def active_legs(db, generation: int | None = None) -> list[dict]:
    generation = generation if generation is not None else current_generation(db)
    rows = db.execute(
        "SELECT al.business_key, bl.* FROM active_legs al JOIN batch_legs bl ON bl.leg_id = al.leg_id "
        "WHERE al.generation = ? ORDER BY al.business_key",
        (generation,),
    ).fetchall()
    return [
        {
            "leg_id": row["leg_id"],
            "batch_id": row["batch_id"],
            "business_key": row["business_key"],
            "content_hash": row["content_hash"],
            "line_no": row["line_no"],
            "payload": json.loads(row["payload"]),
        }
        for row in rows
    ]


def leg_record(db, leg_id: int) -> dict | None:
    row = db.execute("SELECT * FROM batch_legs WHERE leg_id = ?", (leg_id,)).fetchone()
    if not row:
        return None
    return {
        "leg_id": row["leg_id"],
        "batch_id": row["batch_id"],
        "business_key": row["business_key"],
        "content_hash": row["content_hash"],
        "line_no": row["line_no"],
        "payload": json.loads(row["payload"]),
    }


def batch_record(db, batch_id: str) -> dict | None:
    row = db.execute("SELECT * FROM batches WHERE batch_id = ?", (batch_id,)).fetchone()
    return dict(row) if row else None


def list_batches(db) -> list[dict]:
    rows = db.execute(
        "SELECT b.*, (SELECT COUNT(*) FROM batch_legs bl WHERE bl.batch_id = b.batch_id) AS legs, "
        "(SELECT COUNT(*) FROM batch_evidence e WHERE e.batch_id = b.batch_id) AS evidence "
        "FROM batches b ORDER BY b.created_seq DESC"
    ).fetchall()
    return [dict(row) for row in rows]


def superseding_versions(db, batch: dict, business_key: str) -> list[dict]:
    """Later, still-active versions of the same business key.

    Provenance order comes from ``batches.created_seq`` rather than wall-clock
    time so replaying inputs cannot reorder dependencies.
    """
    rows = db.execute(
        "SELECT bl.*, b.created_seq AS batch_seq, b.status AS batch_status FROM batch_legs bl "
        "JOIN batches b ON b.batch_id = bl.batch_id "
        "WHERE bl.business_key = ? AND b.created_seq > ? AND b.status = 'ACTIVE' AND bl.batch_id <> ? "
        "ORDER BY b.created_seq, bl.leg_id",
        (business_key, batch["created_seq"], batch["batch_id"]),
    ).fetchall()
    return [
        {
            "leg_id": row["leg_id"],
            "batch_id": row["batch_id"],
            "created_seq": row["batch_seq"],
            "content_hash": row["content_hash"],
            "line_no": row["line_no"],
            "payload": json.loads(row["payload"]),
        }
        for row in rows
    ]


def predecessor_version(db, batch: dict, business_key: str) -> dict | None:
    """The newest earlier version still owned by an active batch.

    Used when the revoked batch is the *later* one: undoing it re-exposes the
    state it had superseded.  Revoked batches never come back.
    """
    row = db.execute(
        "SELECT bl.*, b.created_seq AS batch_seq FROM batch_legs bl "
        "JOIN batches b ON b.batch_id = bl.batch_id "
        "WHERE bl.business_key = ? AND b.created_seq < ? AND b.status = 'ACTIVE' AND bl.batch_id <> ? "
        "ORDER BY b.created_seq DESC, bl.leg_id DESC LIMIT 1",
        (business_key, batch["created_seq"], batch["batch_id"]),
    ).fetchone()
    if not row:
        return None
    return {
        "leg_id": row["leg_id"],
        "batch_id": row["batch_id"],
        "created_seq": row["batch_seq"],
        "content_hash": row["content_hash"],
        "line_no": row["line_no"],
        "payload": json.loads(row["payload"]),
    }


def batch_legs(db, batch_id: str) -> list[dict]:
    rows = db.execute("SELECT * FROM batch_legs WHERE batch_id = ? ORDER BY leg_id", (batch_id,)).fetchall()
    return [
        {
            "leg_id": row["leg_id"],
            "batch_id": row["batch_id"],
            "business_key": row["business_key"],
            "content_hash": row["content_hash"],
            "line_no": row["line_no"],
            "payload": json.loads(row["payload"]),
        }
        for row in rows
    ]


def batch_evidence(db, batch_id: str) -> list[dict]:
    rows = db.execute(
        "SELECT line_no, reason_code, raw FROM batch_evidence WHERE batch_id = ? ORDER BY line_no", (batch_id,)
    ).fetchall()
    return [{"line_no": row["line_no"], "reason_code": row["reason_code"], "raw": json.loads(row["raw"])} for row in rows]


def allocate_generation(db) -> int:
    """Next free dataset generation.

    A running revocation reserves its staging generation, so an import that
    lands mid-recovery cannot overwrite it; the import instead moves the
    dataset forward and makes the running preview stale.  Every generation that
    ever held data is also skipped, so a superseded staging area is never
    reused by a later job.
    """
    current = current_generation(db)
    job_max = db.execute("SELECT COALESCE(MAX(staging_generation), 0) FROM revocation_jobs").fetchone()[0] or 0
    data_max = db.execute("SELECT COALESCE(MAX(generation), 0) FROM active_legs").fetchone()[0] or 0
    return max(current, job_max, data_max) + 1


def unique_batch_id(db, base_id: str) -> str:
    if not db.execute("SELECT 1 FROM batches WHERE batch_id = ?", (base_id,)).fetchone():
        return base_id
    suffix = 1
    while db.execute("SELECT 1 FROM batches WHERE batch_id = ?", (f"{base_id}~{suffix}",)).fetchone():
        suffix += 1
    return f"{base_id}~{suffix}"


def record_import(db, *, base_batch_id: str, input_sha256: str, accepted: list[dict], quarantine: list[dict]) -> dict:
    """Append one import batch and materialise a new dataset generation.

    Caller owns the transaction.  Repeated content reuses the same active batch
    (idempotent import); a revoked batch is never reused, a fresh batch id is
    allocated instead so re-importing after revocation is a new provenance.
    """
    existing = db.execute(
        "SELECT * FROM batches WHERE batch_id = ? AND status = 'ACTIVE'", (base_batch_id,)
    ).fetchone()
    if existing:
        return {
            "batch_id": existing["batch_id"],
            "created": False,
            "accepted": existing["accepted"],
            "quarantined": existing["quarantined"],
            "generation": current_generation(db),
            "import_seq": import_sequence(db),
        }

    batch_id = unique_batch_id(db, base_batch_id)
    batch_seq = next_meta(db, "batch_sequence")
    base_generation = current_generation(db)
    generation = allocate_generation(db)
    db.execute(
        "INSERT INTO batches(batch_id, input_sha256, rule_version, created_seq, accepted, quarantined, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 'ACTIVE', ?)",
        (batch_id, input_sha256, RULE_VERSION, batch_seq, len(accepted), len(quarantine), now_iso()),
    )

    db.execute(
        "INSERT INTO active_legs(generation, business_key, leg_id) SELECT ?, business_key, leg_id FROM active_legs WHERE generation = ?",
        (generation, base_generation),
    )

    from app.modules.m1_legs.keys import flight_key

    for row in accepted:
        business_key = flight_key(row)
        payload = {key: value for key, value in row.items() if key != "line_no"}
        leg_seq = next_meta(db, "leg_sequence")
        cursor = db.execute(
            "INSERT INTO batch_legs(batch_id, business_key, content_hash, line_no, payload, created_seq, state) "
            "VALUES (?, ?, ?, ?, ?, ?, 'ACTIVE')",
            (batch_id, business_key, content_hash(payload), row["line_no"], canonical(payload), leg_seq),
        )
        leg_id = cursor.lastrowid
        db.execute(
            "INSERT INTO active_legs(generation, business_key, leg_id) VALUES (?, ?, ?) "
            "ON CONFLICT(generation, business_key) DO UPDATE SET leg_id = excluded.leg_id",
            (generation, business_key, leg_id),
        )

    for item in quarantine:
        db.execute(
            "INSERT INTO batch_evidence(batch_id, line_no, reason_code, raw) VALUES (?, ?, ?, ?)",
            (batch_id, item["line_no"], item["reason_code"], canonical(item.get("raw") or {})),
        )

    set_meta(db, "dataset_generation", str(generation))
    seq = next_meta(db, "import_seq")
    return {
        "batch_id": batch_id,
        "created": True,
        "accepted": len(accepted),
        "quarantined": len(quarantine),
        "generation": generation,
        "import_seq": seq,
    }


def copy_generation(db, source_generation: int, target_generation: int) -> None:
    db.execute(
        "INSERT OR REPLACE INTO active_legs(generation, business_key, leg_id) "
        "SELECT ?, business_key, leg_id FROM active_legs WHERE generation = ?",
        (target_generation, source_generation),
    )


def put_active_leg(db, generation: int, business_key: str, leg_id: int) -> None:
    db.execute(
        "INSERT INTO active_legs(generation, business_key, leg_id) VALUES (?, ?, ?) "
        "ON CONFLICT(generation, business_key) DO UPDATE SET leg_id = excluded.leg_id",
        (generation, business_key, leg_id),
    )


def remove_active_leg(db, generation: int, business_key: str) -> None:
    db.execute("DELETE FROM active_legs WHERE generation = ? AND business_key = ?", (generation, business_key))


def active_leg_id(db, generation: int, business_key: str) -> int | None:
    row = db.execute(
        "SELECT leg_id FROM active_legs WHERE generation = ? AND business_key = ?", (generation, business_key)
    ).fetchone()
    return row["leg_id"] if row else None


def ensure_ledger() -> None:
    init_db()


def open_db():
    ensure_ledger()
    return connect()
