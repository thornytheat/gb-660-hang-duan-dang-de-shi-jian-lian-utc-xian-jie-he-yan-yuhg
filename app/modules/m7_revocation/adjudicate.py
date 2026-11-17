"""Adjudication of legs where a later batch changed the same business key.

Both versions are kept; nothing is selected by time order.  A human resolves
each case explicitly.  Decisions:

* ``KEEP_SOURCE`` — the revoked batch's version becomes active again.
* ``KEEP_LATER``  — the later batch's version stays active.
* ``DEFER``       — withhold the key from the rebuilt dataset; both versions
  remain queryable for a later decision.  Deferring is not applying a decision,
  so it is recorded but the key is removed from the new generation.

Source tracking is by provenance: ``batch_legs`` rows never move between
batches, so a later version's dependency on the original batch is explicit.
"""

import hashlib
import json

from app.errors import DomainError
from app.store import transaction

from . import ledger, preview as preview_mod

DECISIONS = ("KEEP_SOURCE", "KEEP_LATER", "DEFER")


def list_adjudications(db, batch_id: str | None = None) -> dict:
    if batch_id:
        rows = preview_mod.adjudications_for_batch(db, batch_id)
    else:
        records = db.execute("SELECT * FROM adjudications ORDER BY created_at").fetchall()
        rows = []
        for record in records:
            item = dict(record)
            item["candidates"] = json.loads(item["candidates"])
            rows.append(item)
    return {"items": rows, "count": len(rows)}


def resolve(db, adjudication_id: str, decision: str, chosen_leg_id: int | None = None) -> dict:
    if decision not in DECISIONS:
        raise DomainError("BAD_DECISION", f"不支持的裁决: {decision}", status=422)
    with transaction(db):
        record = db.execute("SELECT * FROM adjudications WHERE adjudication_id = ?", (adjudication_id,)).fetchone()
        if not record:
            raise DomainError("ADJUDICATION_NOT_FOUND", f"待裁决记录不存在: {adjudication_id}", status=404)
        if record["status"] == "RESOLVED":
            raise DomainError("ADJUDICATION_CLOSED", "该航段已裁决", status=409)

        candidates = json.loads(record["candidates"])
        source_leg_id = candidates[0]["leg_id"]
        later_ids = {item["leg_id"] for item in candidates[1:]}
        if decision == "KEEP_LATER":
            if chosen_leg_id is None:
                raise DomainError("LEG_REQUIRED", "KEEP_LATER 需要指定 chosen_leg_id", status=422)
            if chosen_leg_id not in later_ids:
                raise DomainError("LEG_NOT_CANDIDATE", "chosen_leg_id 必须是后续版本的候选", status=422)
        elif decision == "KEEP_SOURCE":
            if chosen_leg_id is not None and chosen_leg_id != source_leg_id:
                raise DomainError("LEG_NOT_CANDIDATE", "KEEP_SOURCE 只能选择被撤销批次的版本", status=422)
            chosen_leg_id = source_leg_id
        elif decision == "DEFER":
            chosen_leg_id = None

        db.execute(
            "UPDATE adjudications SET status = 'RESOLVED', resolution = ?, chosen_leg_id = ?, resolved_at = ? "
            "WHERE adjudication_id = ?",
            (decision, chosen_leg_id, ledger.now_iso(), adjudication_id),
        )
    row = db.execute("SELECT * FROM adjudications WHERE adjudication_id = ?", (adjudication_id,)).fetchone()
    result = dict(row)
    result["candidates"] = json.loads(row["candidates"])
    return result


def adjudication_id_for(batch_id: str, business_key: str) -> str:
    return "AD-" + hashlib.sha256(f"{batch_id}|{business_key}".encode()).hexdigest()[:12]
