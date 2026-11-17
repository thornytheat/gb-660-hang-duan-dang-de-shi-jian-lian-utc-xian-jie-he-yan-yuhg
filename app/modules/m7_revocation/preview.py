"""Revocation preview: compute the effect of undoing one imported batch.

Rules implemented here:

* Scheduling uses batch provenance (``created_seq``), never wall-clock time.
* A leg whose business key was changed by a later batch is *not* decided by
  time order: both versions are kept as candidates and withheld from the new
  dataset until a human adjudicates.
* A later batch's independent legs are untouched.
* A preview is a snapshot: it records the dataset generation, digest and import
  sequence it was computed against, and becomes stale after any new import or
  dataset change.
"""

import hashlib
import json

from app.errors import DomainError
from app.store import transaction

from . import ledger

REVOCABLE_STATUSES = ("ACTIVE",)


def preview_id_for(batch_id: str, base_generation: int, import_seq: int, digest: str) -> str:
    token = f"{batch_id}|{base_generation}|{import_seq}|{digest}".encode()
    return "PV-" + hashlib.sha256(token).hexdigest()[:12]


def _candidate(leg: dict) -> dict:
    return {
        "leg_id": leg["leg_id"],
        "batch_id": leg["batch_id"],
        "content_hash": leg["content_hash"],
        "line_no": leg["line_no"],
        "payload": leg["payload"],
    }


def build_items(db, batch: dict) -> list[dict]:
    generation = ledger.current_generation(db)
    items = []
    for leg in ledger.batch_legs(db, batch["batch_id"]):
        key = leg["business_key"]
        # Re-importing the exact same content is not a modification; only a
        # genuinely different version needs adjudication.
        later = [
            version
            for version in ledger.superseding_versions(db, batch, key)
            if version["content_hash"] != leg["content_hash"]
        ]
        current_id = ledger.active_leg_id(db, generation, key)
        if later:
            candidates = [_candidate(leg)] + [_candidate(item) for item in later]
            items.append(
                {
                    "business_key": key,
                    "source_leg_id": leg["leg_id"],
                    "current_leg_id": current_id,
                    "action": "ADJUDICATE",
                    "reason": "LATER_BATCH_MODIFIED_SAME_LEG",
                    "candidates": candidates,
                }
            )
        elif current_id == leg["leg_id"]:
            previous = ledger.predecessor_version(db, batch, key)
            if previous:
                items.append(
                    {
                        "business_key": key,
                        "source_leg_id": leg["leg_id"],
                        "current_leg_id": current_id,
                        "action": "RESTORE",
                        "reason": "REVOKED_VERSION_SUPERSEDED_EARLIER_ONE",
                        "restore_leg_id": previous["leg_id"],
                        "candidates": [_candidate(leg), _candidate(previous)],
                    }
                )
            else:
                items.append(
                    {
                        "business_key": key,
                        "source_leg_id": leg["leg_id"],
                        "current_leg_id": current_id,
                        "action": "REVOKE",
                        "reason": "SOURCE_VERSION_ACTIVE",
                        "candidates": [_candidate(leg)],
                    }
                )
        else:
            items.append(
                {
                    "business_key": key,
                    "source_leg_id": leg["leg_id"],
                    "current_leg_id": current_id,
                    "action": "RETAIN",
                    "reason": "SOURCE_VERSION_NOT_ACTIVE",
                    "candidates": [_candidate(leg)],
                }
            )
    return items


def _plan_counts(items: list[dict]) -> dict:
    counts = {"total": len(items), "revoke": 0, "restore": 0, "retain": 0, "adjudicate": 0}
    for item in items:
        counts[item["action"].lower()] += 1
    return counts


def create_preview(db, batch_id: str) -> dict:
    batch = ledger.batch_record(db, batch_id)
    if not batch:
        raise DomainError("BATCH_NOT_FOUND", f"批次不存在: {batch_id}", status=404)
    if batch["status"] not in REVOCABLE_STATUSES:
        raise DomainError("BATCH_ALREADY_REVOKED", f"批次已撤销: {batch_id}", status=409)

    base_generation = ledger.current_generation(db)
    import_seq = ledger.import_sequence(db)
    digest = ledger.dataset_digest(db, base_generation)
    preview_id = preview_id_for(batch_id, base_generation, import_seq, digest)

    existing = db.execute("SELECT * FROM revocation_previews WHERE preview_id = ?", (preview_id,)).fetchone()
    if existing:
        return serialize_preview(existing)

    items = build_items(db, batch)
    if not items:
        # Revoking a batch that contributed no accepted leg would switch in an
        # identical generation for nothing; reject it explicitly instead.
        raise DomainError("BATCH_HAS_NO_LEGS", f"批次没有可撤销的采纳航段: {batch_id}", status=409)
    plan = {
        "batch_id": batch_id,
        "base_generation": base_generation,
        "import_seq": import_seq,
        "dataset_digest": digest,
        "items": items,
        "counts": _plan_counts(items),
    }
    created_at = ledger.now_iso()
    with transaction(db):
        db.execute(
            "INSERT INTO revocation_previews(preview_id, batch_id, import_seq, base_generation, dataset_digest, plan, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'VALID', ?)",
            (preview_id, batch_id, import_seq, base_generation, digest, ledger.canonical(plan), created_at),
        )
        for item in items:
            if item["action"] != "ADJUDICATE":
                continue
            adjudication_id = "AD-" + hashlib.sha256(f"{batch_id}|{item['business_key']}".encode()).hexdigest()[:12]
            candidates_json = ledger.canonical(item["candidates"])
            existing_adjudication = db.execute(
                "SELECT status, candidates FROM adjudications WHERE adjudication_id = ?", (adjudication_id,)
            ).fetchone()
            if existing_adjudication and existing_adjudication["status"] == "RESOLVED":
                if existing_adjudication["candidates"] == candidates_json:
                    # Same candidate set: keep the human decision, just re-anchor
                    # it to the preview that execution will use.
                    db.execute(
                        "UPDATE adjudications SET preview_id = ? WHERE adjudication_id = ?",
                        (preview_id, adjudication_id),
                    )
                    continue
                # New versions appeared, so the earlier decision no longer covers
                # the case; reopen it rather than silently reusing a stale choice.
            db.execute(
                "INSERT INTO adjudications(adjudication_id, batch_id, business_key, preview_id, candidates, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, 'OPEN', ?) "
                "ON CONFLICT(adjudication_id) DO UPDATE SET preview_id = excluded.preview_id, "
                "candidates = excluded.candidates, status = 'OPEN', resolution = NULL, chosen_leg_id = NULL, resolved_at = NULL",
                (adjudication_id, batch_id, item["business_key"], preview_id, candidates_json, created_at),
            )
    row = db.execute("SELECT * FROM revocation_previews WHERE preview_id = ?", (preview_id,)).fetchone()
    return serialize_preview(row)


def serialize_preview(row) -> dict:
    plan = json.loads(row["plan"])
    return {
        "preview_id": row["preview_id"],
        "batch_id": row["batch_id"],
        "status": row["status"],
        "created_at": row["created_at"],
        "base_generation": row["base_generation"],
        "import_seq": row["import_seq"],
        "dataset_digest": row["dataset_digest"],
        "counts": plan["counts"],
        "items": plan["items"],
    }


def is_stale(db, preview: dict) -> bool:
    if preview["status"] != "VALID":
        return True
    if ledger.current_generation(db) != preview["base_generation"]:
        return True
    if ledger.import_sequence(db) != preview["import_seq"]:
        return True
    return ledger.dataset_digest(db, preview["base_generation"]) != preview["dataset_digest"]


def mark_stale(db, preview_id: str) -> None:
    db.execute("UPDATE revocation_previews SET status = 'STALE' WHERE preview_id = ?", (preview_id,))


def get_preview(db, preview_id: str) -> dict:
    row = db.execute("SELECT * FROM revocation_previews WHERE preview_id = ?", (preview_id,)).fetchone()
    if not row:
        raise DomainError("PREVIEW_NOT_FOUND", f"预演不存在: {preview_id}", status=404)
    return dict(row)


def adjudication_record(db, adjudication_id: str) -> dict | None:
    row = db.execute("SELECT * FROM adjudications WHERE adjudication_id = ?", (adjudication_id,)).fetchone()
    return dict(row) if row else None


def adjudications_for_batch(db, batch_id: str) -> list[dict]:
    rows = db.execute(
        "SELECT * FROM adjudications WHERE batch_id = ? ORDER BY business_key", (batch_id,)
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["candidates"] = json.loads(item["candidates"])
        result.append(item)
    return result
