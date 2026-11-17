"""Resumable execution of a revocation preview.

The new dataset is built in a *staging generation*; the current generation
(and therefore every existing itinerary/connection read) stays untouched until
a single atomic switch.  Each item is applied in its own transaction together
with the job cursor, so a crash resumes at the next item and a re-applied item
is idempotent.  Applying is expressed as set/remove of a business key, never as
"undo once", so retries cannot double-revoke.
"""

import json

from app.errors import DomainError
from app.store import transaction

from . import ledger, preview as preview_mod


def _job_row(db, job_id: str):
    row = db.execute("SELECT * FROM revocation_jobs WHERE job_id = ?", (job_id,)).fetchone()
    if not row:
        raise DomainError("JOB_NOT_FOUND", f"撤销任务不存在: {job_id}", status=404)
    return row


def _serialize_job(db, row) -> dict:
    preview = db.execute("SELECT * FROM revocation_previews WHERE preview_id = ?", (row["preview_id"],)).fetchone()
    items = db.execute(
        "SELECT business_key, action, state, detail FROM revocation_items WHERE job_id = ? ORDER BY item_index",
        (row["job_id"],),
    ).fetchall()
    return {
        "job_id": row["job_id"],
        "batch_id": row["batch_id"],
        "preview_id": row["preview_id"],
        "status": row["status"],
        "cursor": row["cursor"],
        "staging_generation": row["staging_generation"],
        "base_generation": preview["base_generation"] if preview else None,
        "current_generation": ledger.current_generation(db),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "items": [dict(item) for item in items],
        "report": json.loads(row["report"]) if row["report"] else None,
    }


def serialize_job(db, job_id: str) -> dict:
    return _serialize_job(db, _job_row(db, job_id))


def _adjudication_map(db, batch_id: str) -> dict:
    return {item["business_key"]: item for item in preview_mod.adjudications_for_batch(db, batch_id)}


def execute(db, preview_id: str, limit: int | None = None) -> dict:
    preview = preview_mod.get_preview(db, preview_id)
    # A finished job is returned as-is even though finalisation consumed the
    # preview; retrying a completed revocation must not raise nor re-apply.
    done = db.execute(
        "SELECT job_id FROM revocation_jobs WHERE preview_id = ? AND status = 'DONE'", (preview_id,)
    ).fetchone()
    if done:
        return _serialize_job(db, _job_row(db, done["job_id"]))

    # An interrupted run resumes before freshness is re-checked, so the
    # resume path can itself detect a mid-run import and supersede the job.
    running = db.execute(
        "SELECT job_id FROM revocation_jobs WHERE preview_id = ? AND status = 'RUNNING'", (preview_id,)
    ).fetchone()
    if running:
        return _run_job(db, running["job_id"], limit)

    if preview["status"] != "VALID":
        raise DomainError("PREVIEW_STALE", "预演已失效，请重新预演", status=409)
    if preview_mod.is_stale(db, preview):
        with transaction(db):
            preview_mod.mark_stale(db, preview_id)
        raise DomainError("PREVIEW_STALE", "预演后有新导入或数据变更，请重新预演", status=409)

    plan = json.loads(preview["plan"])
    adjudications = _adjudication_map(db, preview["batch_id"])
    open_keys = [
        item["business_key"]
        for item in plan["items"]
        if item["action"] == "ADJUDICATE"
        and (adjudications.get(item["business_key"]) or {}).get("status") != "RESOLVED"
    ]
    if open_keys:
        raise DomainError(
            "CONFLICTS_PENDING",
            f"存在 {len(open_keys)} 条待裁决航段，请先裁决",
            status=409,
        )

    job_id = _create_job(db, preview, plan, adjudications)
    return _run_job(db, job_id, limit)


def _create_job(db, preview, plan: dict, adjudications: dict) -> str:
    job_id = "JB-" + ledger.content_hash(
        {"preview": preview["preview_id"], "token": ledger.current_generation(db)}
    )[:12]
    now = ledger.now_iso()
    with transaction(db):
        # Two concurrent execute calls both see "no job" outside the
        # transaction; the write lock serialises them, so the loser reuses the
        # job the winner created instead of colliding on job_id.
        existing = db.execute(
            "SELECT job_id, status FROM revocation_jobs WHERE preview_id = ? ORDER BY created_at LIMIT 1",
            (preview["preview_id"],),
        ).fetchone()
        if existing:
            return existing["job_id"]
        staging = ledger.allocate_generation(db)
        db.execute(
            "INSERT INTO revocation_jobs(job_id, batch_id, preview_id, staging_generation, status, cursor, checkpoint, report, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'RUNNING', 0, '{}', NULL, ?, ?)",
            (job_id, preview["batch_id"], preview["preview_id"], staging, now, now),
        )
        # Seed staging from the generation the preview was computed on.  A
        # resumed job keeps whatever it already staged.
        ledger.copy_generation(db, preview["base_generation"], staging)
        for index, item in enumerate(plan["items"]):
            adjudication = adjudications.get(item["business_key"]) or {}
            detail = {"index": index, "source_leg_id": item["source_leg_id"]}
            if item.get("restore_leg_id") is not None:
                detail["restore_leg_id"] = item["restore_leg_id"]
            if adjudication.get("status") == "RESOLVED":
                detail["resolution"] = {
                    "decision": adjudication["resolution"],
                    "leg_id": adjudication["chosen_leg_id"],
                }
            db.execute(
                "INSERT INTO revocation_items(job_id, item_index, business_key, action, state, detail) VALUES (?, ?, ?, ?, 'PENDING', ?)",
                (job_id, index, item["business_key"], item["action"], ledger.canonical(detail)),
            )
    return job_id


def _apply_item(db, staging: int, row) -> str:
    key = row["business_key"]
    detail = json.loads(row["detail"])
    action = row["action"]
    if action == "REVOKE":
        ledger.remove_active_leg(db, staging, key)
        return "REVOKED"
    if action == "RESTORE":
        restore_id = detail.get("restore_leg_id")
        if restore_id is None:
            raise DomainError("BAD_PLAN", f"RESTORE 缺少被恢复版本: {key}", status=500)
        ledger.put_active_leg(db, staging, key, int(restore_id))
        return "RESTORED"
    if action == "RETAIN":
        return "RETAINED"
    if action == "ADJUDICATE":
        resolution = detail.get("resolution") or {}
        decision = resolution.get("decision")
        if decision == "KEEP_LATER" and resolution.get("leg_id") is not None:
            ledger.put_active_leg(db, staging, key, int(resolution["leg_id"]))
            return "RETAINED"
        if decision == "KEEP_SOURCE" and detail.get("source_leg_id") is not None:
            ledger.put_active_leg(db, staging, key, int(detail["source_leg_id"]))
            return "RETAINED"
        # DEFER: withhold the key and keep both versions queryable.
        ledger.remove_active_leg(db, staging, key)
        return "PENDING_ADJUDICATION"
    raise DomainError("BAD_ACTION", f"未知撤销动作: {action}", status=500)


def _run_job(db, job_id: str, limit: int | None = None) -> dict:
    job = _job_row(db, job_id)
    if job["status"] == "DONE":
        return _serialize_job(db, job)
    if job["status"] in ("SUPERSEDED", "FAILED"):
        raise DomainError("JOB_NOT_RUNNABLE", f"撤销任务状态为 {job['status']}，不能继续执行", status=409)
    preview = preview_mod.get_preview(db, job["preview_id"])
    staging = job["staging_generation"]
    rows = db.execute(
        "SELECT * FROM revocation_items WHERE job_id = ? AND state = 'PENDING' AND item_index >= ? ORDER BY item_index",
        (job_id, job["cursor"]),
    ).fetchall()
    processed = 0
    for row in rows:
        # A new import or external dataset change while recovering invalidates
        # the remaining plan; stop before touching the staging generation.
        if preview_mod.is_stale(db, preview):
            preview_mod.mark_stale(db, job["preview_id"])
            with transaction(db):
                db.execute(
                    "UPDATE revocation_jobs SET status = 'SUPERSEDED', updated_at = ? WHERE job_id = ?",
                    (ledger.now_iso(), job_id),
                )
            raise DomainError("PREVIEW_STALE", "执行期间出现新导入或数据变更，撤销任务作废，请重新预演", status=409)
        if limit is not None and processed >= limit:
            break
        detail = json.loads(row["detail"])
        with transaction(db):
            outcome = _apply_item(db, staging, row)
            detail["outcome"] = outcome
            db.execute(
                "UPDATE revocation_items SET state = 'DONE', detail = ? WHERE job_id = ? AND business_key = ?",
                (ledger.canonical(detail), job_id, row["business_key"]),
            )
            db.execute(
                "UPDATE revocation_jobs SET cursor = ?, updated_at = ? WHERE job_id = ?",
                (detail["index"] + 1, ledger.now_iso(), job_id),
            )
        processed += 1
    remaining = db.execute(
        "SELECT COUNT(*) FROM revocation_items WHERE job_id = ? AND state = 'PENDING'", (job_id,)
    ).fetchone()[0]
    if remaining:
        return _serialize_job(db, _job_row(db, job_id))
    return _finalize(db, job_id)


def retry(db, job_id: str, limit: int | None = None) -> dict:
    """Resume an interrupted job; a finished job is returned as-is."""
    job = _job_row(db, job_id)
    if job["status"] == "DONE":
        return _serialize_job(db, job)
    if job["status"] != "RUNNING":
        raise DomainError("JOB_NOT_RUNNABLE", f"撤销任务状态为 {job['status']}，不能继续执行", status=409)
    return _run_job(db, job_id, limit)


def _finalize(db, job_id: str) -> dict:
    job = _job_row(db, job_id)
    if job["status"] == "DONE":
        return _serialize_job(db, job)
    preview = preview_mod.get_preview(db, job["preview_id"])
    now = ledger.now_iso()

    # Freshness check, conservation read and the switch all happen under one
    # write lock, so an import cannot slip in between the check and the switch.
    with transaction(db):
        job = _job_row(db, job_id)
        batch = ledger.batch_record(db, job["batch_id"])
        if not batch or batch["status"] != "ACTIVE":
            _supersede(db, job_id)
            error = DomainError("BATCH_ALREADY_REVOKED", "批次已不在活动状态，撤销任务作废", status=409)
        elif preview_mod.is_stale(db, preview):
            preview_mod.mark_stale(db, preview["preview_id"])
            _supersede(db, job_id)
            error = DomainError("PREVIEW_STALE", "执行期间出现新导入或数据变更，撤销任务作废，请重新预演", status=409)
        else:
            error = None
            staging = job["staging_generation"]
            plan = json.loads(preview["plan"])
            before = ledger.active_legs(db, preview["base_generation"])
            after = ledger.active_legs(db, staging)
            attributable = {row["business_key"] for row in ledger.batch_legs(db, job["batch_id"])}
            allowed_leg_ids = {row["leg_id"] for row in ledger.batch_legs(db, job["batch_id"])}
            for item in plan["items"]:
                for candidate in item["candidates"]:
                    allowed_leg_ids.add(candidate["leg_id"])
                if item.get("restore_leg_id") is not None:
                    allowed_leg_ids.add(item["restore_leg_id"])
            conservation = _conservation(before, after, attributable, allowed_leg_ids)
            chain = recompute_connections(after)
            report = {
                "before_generation": preview["base_generation"],
                "after_generation": staging,
                "conservation": conservation,
                "chain": chain,
            }
            # Atomic switch: the only statement that makes the new generation
            # visible; batch and preview state move with it.
            db.execute("UPDATE meta SET value = ? WHERE key = 'dataset_generation'", (str(staging),))
            db.execute("UPDATE batches SET status = 'REVOKED', revoked_at = ? WHERE batch_id = ?", (now, job["batch_id"]))
            db.execute("UPDATE revocation_previews SET status = 'CONSUMED' WHERE batch_id = ? AND status = 'VALID'", (job["batch_id"],))
            total = db.execute("SELECT COUNT(*) FROM revocation_items WHERE job_id = ?", (job_id,)).fetchone()[0]
            db.execute(
                "UPDATE revocation_jobs SET status = 'DONE', cursor = ?, report = ?, updated_at = ? WHERE job_id = ?",
                (total, ledger.canonical(report), now, job_id),
            )
    if error:
        raise error
    return _serialize_job(db, _job_row(db, job_id))


def _supersede(db, job_id: str) -> None:
    db.execute(
        "UPDATE revocation_jobs SET status = 'SUPERSEDED', updated_at = ? WHERE job_id = ?",
        (ledger.now_iso(), job_id),
    )


def _conservation(
    before: list[dict],
    after: list[dict],
    attributable_keys: set[str] | None = None,
    allowed_leg_ids: set[int] | None = None,
) -> dict:
    """Compare the pre- and post-switch dataset.

    A revocation may only remove keys or switch a contested key between two
    known versions; it must never introduce a business key.  ``balanced`` is
    that CLOSED-WORLD invariant, ``accounted`` proves every touched key traces
    to the revoked batch or to a candidate of a contested leg.
    """
    before_keys = {row["business_key"]: row for row in before}
    after_keys = {row["business_key"]: row for row in after}
    removed = sorted(set(before_keys) - set(after_keys))
    added = sorted(set(after_keys) - set(before_keys))
    changed = sorted(
        key for key in set(before_keys) & set(after_keys)
        if before_keys[key]["content_hash"] != after_keys[key]["content_hash"]
    )
    delta = len(before) - len(after)
    balanced = not added and delta == len(removed)

    unaccounted = []
    if attributable_keys is not None:
        unaccounted.extend(key for key in removed if key not in attributable_keys)
    if allowed_leg_ids is not None:
        for key in added + changed:
            if after_keys[key]["leg_id"] not in allowed_leg_ids:
                unaccounted.append(key)

    return {
        "before": len(before),
        "after": len(after),
        "removed": len(removed),
        "added": len(added),
        "version_changes": len(changed),
        "delta": delta,
        "balanced": balanced,
        "accounted": not unaccounted,
        "unaccounted_keys": sorted(set(unaccounted)),
        "removed_keys": removed,
        "added_keys": added,
        "changed_keys": changed,
    }


def recompute_connections(legs: list[dict]) -> dict:
    """Rebuild the UTC chain of the new generation and recheck connections."""
    from datetime import datetime

    from app.modules.m2_airports.registry import AIRPORTS
    from app.modules.m4_itinerary.builder import build_leg, order_legs
    from app.modules.m4_itinerary.validate import validate_chain
    from app.modules.m5_connections.rules import connection_result, required_minutes
    from app.modules.m5_connections.windows import waiting_minutes

    built, rejected = [], []
    for row in legs:
        payload = row["payload"]
        try:
            leg = build_leg(
                {
                    "flight_no": payload["flight_no"],
                    "origin": payload["origin"],
                    "destination": payload["destination"],
                    "departure_local": payload["departure_local"],
                    "arrival_local": payload["arrival_local"],
                    "departure_fold": payload.get("departure_fold"),
                    "arrival_fold": payload.get("arrival_fold"),
                }
            )
        except ValueError as exc:
            rejected.append({"business_key": row["business_key"], "reason_code": str(exc)})
            continue
        leg["business_key"] = row["business_key"]
        built.append(leg)

    ordered = order_legs(built)
    connections = []
    for index in range(len(ordered) - 1):
        left, right = ordered[index], ordered[index + 1]
        if left["destination"] != right["origin"]:
            continue
        airport = right["origin"]
        terminal = AIRPORTS.get(airport, [(None, None, None, "?")])[0][3]
        wait = waiting_minutes(
            datetime.fromisoformat(left["arrival_utc"]), datetime.fromisoformat(right["departure_utc"])
        )
        result = connection_result(wait, required_minutes(airport, terminal, terminal), 720)
        result.update({"airport": airport, "from": left["business_key"], "to": right["business_key"]})
        connections.append(result)

    span = 0
    if ordered:
        span = int(
            (datetime.fromisoformat(ordered[-1]["arrival_utc"]) - datetime.fromisoformat(ordered[0]["departure_utc"])).total_seconds()
            // 60
        )
    return {
        "legs": len(legs),
        "connectable": len(built),
        "rejected": len(rejected),
        "rejected_detail": rejected,
        "chain_valid": validate_chain(ordered) if ordered else False,
        "chain_span_minutes": span,
        "connections": connections,
        "balanced": len(legs) == len(built) + len(rejected),
    }


def readback(db, job_id: str) -> dict:
    job = _job_row(db, job_id)
    preview = preview_mod.get_preview(db, job["preview_id"])
    done = job["status"] == "DONE"
    generation = job["staging_generation"] if done else preview["base_generation"]
    active = {row["business_key"]: row for row in ledger.active_legs(db, generation)}
    base = {row["business_key"]: row for row in ledger.active_legs(db, preview["base_generation"])}

    rows = db.execute(
        "SELECT * FROM revocation_items WHERE job_id = ? ORDER BY item_index", (job_id,)
    ).fetchall()
    revoked, retained, restored, pending = [], [], [], []
    for row in rows:
        detail = json.loads(row["detail"])
        outcome = detail.get("outcome")
        key = row["business_key"]
        entry = {
            "business_key": key,
            "action": row["action"],
            "outcome": outcome,
            "source_leg_id": detail.get("source_leg_id"),
            "active_leg_id": active.get(key, {}).get("leg_id"),
            "state": row["state"],
        }
        if outcome == "REVOKED":
            revoked.append(entry)
        elif outcome == "PENDING_ADJUDICATION":
            pending.append(entry)
        elif outcome == "RESTORED":
            restored.append(entry)
        elif row["state"] == "DONE":
            retained.append(entry)

    report = json.loads(job["report"]) if job["report"] else None
    return {
        "job": _serialize_job(db, job),
        "batch_id": job["batch_id"],
        "generation": generation,
        "current_generation": ledger.current_generation(db),
        "revoked_legs": revoked,
        "restored_legs": restored,
        "retained_legs": retained,
        "pending_adjudication": pending,
        "adjudications": preview_mod.adjudications_for_batch(db, job["batch_id"]),
        "conservation": report["conservation"] if report else _conservation(list(base.values()), list(active.values())),
        "chain": report["chain"] if report else recompute_connections(list(active.values())),
        "old_chain_readable": not done,
    }
