from app.manifest import build_manifest
from app.store import transaction
from app.modules.m7_revocation import ledger

from .parser import parse_csv_legs, parse_legs
from .keys import flight_key

SAMPLE = [{"flight_no": "mu5101", "flight_date": "2026-11-16", "origin": "pvg", "destination": "jfk", "departure_local": "2026-11-16T09:00", "arrival_local": "2026-11-16T10:30"}]
SAMPLE_BYTES = b"flight_no,flight_date,origin,destination,departure_local,arrival_local\nMU5101,2026-11-16,PVG,JFK,2026-11-16T09:00,2026-11-16T10:30\n"


def _import(payload: bytes, accepted: list[dict], quarantine: list[dict]) -> dict:
    manifest = build_manifest(payload, len(accepted), len(quarantine))
    db = ledger.open_db()
    try:
        with transaction(db):
            result = ledger.record_import(
                db,
                base_batch_id=manifest["run_id"],
                input_sha256=manifest["input_sha256"],
                accepted=accepted,
                quarantine=quarantine,
            )
    finally:
        db.close()
    return {
        **manifest,
        "batch_id": result["batch_id"],
        "created": result["created"],
        "input": len(accepted) + len(quarantine),
        "accepted": len(accepted),
        "quarantined": len(quarantine),
        "keys": [flight_key(row) for row in accepted],
        "evidence": quarantine,
        "generation": result["generation"],
        "import_seq": result["import_seq"],
    }


def import_csv(text: str) -> dict:
    accepted, quarantine = parse_csv_legs(text)
    return _import(text.encode("utf-8"), accepted, quarantine)


def import_rows(rows: list[dict]) -> dict:
    accepted, quarantine = parse_legs(rows)
    payload = ledger.canonical(rows).encode("utf-8")
    return _import(payload, accepted, quarantine)


def run(rows: list[dict] | None = None) -> dict:
    if rows is None:
        return import_csv(SAMPLE_BYTES.decode("utf-8"))
    return import_rows(rows)


def demo():
    return run()
