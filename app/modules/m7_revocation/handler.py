from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.errors import DomainError
from app.web import page
from . import adjudicate, executor, ledger
from .preview import create_preview, serialize_preview

router = APIRouter()

ROWS = [
    {"key": "BATCH-IMPORT-1", "status": "误导入", "value": "3 航段"},
    {"key": "BATCH-IMPORT-2", "status": "独立后续", "value": "保留"},
    {"key": "MU5101|2026-11-16", "status": "两版待裁决", "value": "AD-…"},
]


@router.get("/revocations", response_class=HTMLResponse)
def view(request: Request):
    return page(request, "m7.html", "批次撤销", "/api/revocations/batches", ROWS)


@router.get("/api/revocations/batches")
def batches():
    db = ledger.open_db()
    try:
        return {"items": ledger.list_batches(db)}
    finally:
        db.close()


@router.post("/api/revocations/batches/{batch_id}/preview")
def preview_batch(batch_id: str):
    db = ledger.open_db()
    try:
        return create_preview(db, batch_id)
    finally:
        db.close()


@router.get("/api/revocations/previews/{preview_id}")
def read_preview(preview_id: str):
    db = ledger.open_db()
    try:
        row = db.execute("SELECT * FROM revocation_previews WHERE preview_id = ?", (preview_id,)).fetchone()
        if not row:
            raise DomainError("PREVIEW_NOT_FOUND", f"预演不存在: {preview_id}", status=404)
        return serialize_preview(row)
    finally:
        db.close()


@router.post("/api/revocations/previews/{preview_id}/execute")
def execute_preview(preview_id: str, body: dict | None = None):
    db = ledger.open_db()
    try:
        limit = (body or {}).get("limit")
        return executor.execute(db, preview_id, limit=limit)
    finally:
        db.close()


@router.post("/api/revocations/previews/{preview_id}/simulate-crash")
def simulate_crash(preview_id: str, body: dict | None = None):
    """Test hook: process ``limit`` items then stop, leaving the job RUNNING."""
    db = ledger.open_db()
    try:
        limit = (body or {}).get("limit", 1)
        return executor.execute(db, preview_id, limit=limit)
    finally:
        db.close()


@router.post("/api/revocations/jobs/{job_id}/retry")
def retry_job(job_id: str, body: dict | None = None):
    db = ledger.open_db()
    try:
        return executor.retry(db, job_id, limit=(body or {}).get("limit"))
    finally:
        db.close()


@router.get("/api/revocations/jobs/{job_id}")
def read_job(job_id: str):
    db = ledger.open_db()
    try:
        return executor.readback(db, job_id)
    finally:
        db.close()


@router.get("/api/revocations/adjudications")
def adjudications(batch_id: str | None = None):
    db = ledger.open_db()
    try:
        return adjudicate.list_adjudications(db, batch_id)
    finally:
        db.close()


@router.post("/api/revocations/adjudications/{adjudication_id}/resolve")
def resolve(adjudication_id: str, body: dict):
    db = ledger.open_db()
    try:
        return adjudicate.resolve(db, adjudication_id, body.get("decision", ""), body.get("chosen_leg_id"))
    finally:
        db.close()


@router.get("/api/revocations/legs")
def active_legs(generation: int | None = None):
    db = ledger.open_db()
    try:
        return {
            "generation": generation if generation is not None else ledger.current_generation(db),
            "current_generation": ledger.current_generation(db),
            "items": ledger.active_legs(db, generation),
        }
    finally:
        db.close()


@router.get("/api/revocations/chain")
def chain(generation: int | None = None):
    """Read the UTC chain of any generation, including one kept live during a
    recovery run."""
    db = ledger.open_db()
    try:
        target = generation if generation is not None else ledger.current_generation(db)
        legs = ledger.active_legs(db, target)
        return {
            "generation": target,
            "current_generation": ledger.current_generation(db),
            "chain": executor.recompute_connections(legs),
        }
    finally:
        db.close()
