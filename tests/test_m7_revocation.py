import pytest

from app.errors import DomainError
from app.modules.m1_legs import service as legs_service
from app.modules.m7_revocation import adjudicate, executor, ledger
from app.modules.m7_revocation.preview import create_preview

HEADER = "flight_no,flight_date,origin,destination,departure_local,arrival_local,departure_fold,arrival_fold\n"


def csv_text(*rows: str) -> str:
    return HEADER + "".join(row + "\n" for row in rows)


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    import app.store as store

    monkeypatch.setattr(store, "DATABASE_PATH", tmp_path / "ledger.sqlite3")
    store.init_db()
    return store


GOOD = "MU5101,2026-11-16,PVG,JFK,2026-11-16T09:00,2026-11-16T10:30,,"


def test_import_persists_real_legs_and_evidence(isolated):
    result = legs_service.import_csv(
        csv_text(GOOD, "AF001,2026-11-18,JFK,LHR,,2026-11-18T09:00,,")
    )
    assert result["accepted"] == 1 and result["quarantined"] == 1
    db = isolated.connect()
    try:
        active = ledger.active_legs(db, result["generation"])
        assert [row["business_key"] for row in active] == ["MU5101|2026-11-16|PVG|JFK"]
        evidence = ledger.batch_evidence(db, result["batch_id"])
        assert evidence[0]["reason_code"] == "EMPTY_VALUE" and evidence[0]["line_no"] == 3
    finally:
        db.close()


def test_import_is_idempotent_for_same_bytes(isolated):
    first = legs_service.import_csv(csv_text(GOOD))
    second = legs_service.import_csv(csv_text(GOOD))
    assert first["batch_id"] == second["batch_id"] and not second["created"]


def test_truncated_tail_quarantined(isolated):
    result = legs_service.import_csv(HEADER + GOOD + "\nUA857,2026-11-01,JFK,SFO,2026-11-0")
    assert result["quarantined"] == 1
    assert any(item["reason_code"] == "TRUNCATED_TAIL" for item in result["evidence"])


def _two_batches(isolated):
    first = legs_service.import_csv(
        csv_text(
            "MU5101,2026-11-16,PVG,JFK,2026-11-16T09:00,2026-11-16T10:30,,",
            "CA981,2026-11-17,PEK,LHR,2026-11-17T12:00,2026-11-17T20:00,,",
        )
    )
    second = legs_service.import_csv(
        csv_text("UA857,2026-11-19,SFO,LHR,2026-11-19T09:00,2026-11-19T17:00,,")
    )
    return first, second


def test_preview_keeps_independent_later_legs(isolated):
    first, second = _two_batches(isolated)
    db = isolated.connect()
    try:
        preview = create_preview(db, first["batch_id"])
    finally:
        db.close()
    assert preview["counts"] == {"total": 2, "revoke": 2, "restore": 0, "retain": 0, "adjudicate": 0}


def test_later_change_creates_two_candidates_not_time_choice(isolated):
    first = legs_service.import_csv(csv_text(GOOD))
    second = legs_service.import_csv(
        csv_text("MU5101,2026-11-16,PVG,JFK,2026-11-16T09:30,2026-11-16T11:00,,")
    )
    assert second["created"] and second["batch_id"] != first["batch_id"]
    db = isolated.connect()
    try:
        preview = create_preview(db, first["batch_id"])
    finally:
        db.close()
    assert preview["counts"]["adjudicate"] == 1
    item = preview["items"][0]
    assert item["action"] == "ADJUDICATE"
    assert [candidate["batch_id"] for candidate in item["candidates"]] == [first["batch_id"], second["batch_id"]]
    chosen = item["candidates"][0]["payload"]["departure_local"]
    other = item["candidates"][1]["payload"]["departure_local"]
    assert {chosen, other} == {"2026-11-16T09:00", "2026-11-16T09:30"}


def test_execute_blocked_until_adjudicated(isolated):
    first = legs_service.import_csv(csv_text(GOOD))
    legs_service.import_csv(csv_text("MU5101,2026-11-16,PVG,JFK,2026-11-16T09:30,2026-11-16T11:00,,"))
    db = isolated.connect()
    try:
        preview = create_preview(db, first["batch_id"])
        with pytest.raises(DomainError) as error:
            executor.execute(db, preview["preview_id"])
        assert error.value.code == "CONFLICTS_PENDING"
    finally:
        db.close()


def test_adjudication_keep_later_retains_later_version(isolated):
    first = legs_service.import_csv(csv_text(GOOD))
    legs_service.import_csv(csv_text("MU5101,2026-11-16,PVG,JFK,2026-11-16T09:30,2026-11-16T11:00,,"))
    db = isolated.connect()
    try:
        preview = create_preview(db, first["batch_id"])
        cases = adjudicate.list_adjudications(db, first["batch_id"])["items"]
        assert cases[0]["status"] == "OPEN"
        later = [c for c in cases[0]["candidates"] if c["batch_id"] != first["batch_id"]][0]
        adjudicate.resolve(db, cases[0]["adjudication_id"], "KEEP_LATER", later["leg_id"])
        job = executor.execute(db, preview["preview_id"])
        readback = executor.readback(db, job["job_id"])
    finally:
        db.close()
    assert job["status"] == "DONE"
    by_key = {row["business_key"]: row for row in readback["retained_legs"]}
    assert readback["revoked_legs"] == []
    assert by_key["MU5101|2026-11-16|PVG|JFK"]["active_leg_id"] == later["leg_id"]


def test_adjudication_defer_withholds_both_versions(isolated):
    first = legs_service.import_csv(csv_text(GOOD))
    legs_service.import_csv(csv_text("MU5101,2026-11-16,PVG,JFK,2026-11-16T09:30,2026-11-16T11:00,,"))
    db = isolated.connect()
    try:
        preview = create_preview(db, first["batch_id"])
        case = adjudicate.list_adjudications(db, first["batch_id"])["items"][0]
        adjudicate.resolve(db, case["adjudication_id"], "DEFER")
        job = executor.execute(db, preview["preview_id"])
        readback = executor.readback(db, job["job_id"])
        current = ledger.active_legs(db)
    finally:
        db.close()
    assert readback["pending_adjudication"][0]["business_key"] == "MU5101|2026-11-16|PVG|JFK"
    assert current == []


def test_execute_removes_source_and_keeps_later_independent_leg(isolated):
    first, second = _two_batches(isolated)
    db = isolated.connect()
    try:
        preview = create_preview(db, first["batch_id"])
        job = executor.execute(db, preview["preview_id"])
        readback = executor.readback(db, job["job_id"])
        current = ledger.active_legs(db)
    finally:
        db.close()
    assert job["status"] == "DONE"
    assert {row["business_key"] for row in readback["revoked_legs"]} == {
        "MU5101|2026-11-16|PVG|JFK",
        "CA981|2026-11-17|PEK|LHR",
    }
    assert [row["business_key"] for row in current] == ["UA857|2026-11-19|SFO|LHR"]
    assert readback["conservation"]["delta"] == 2
    assert readback["conservation"]["balanced"]


def test_new_import_after_preview_rejects_execution(isolated):
    first, _second = _two_batches(isolated)
    db = isolated.connect()
    try:
        preview = create_preview(db, first["batch_id"])
        legs_service.import_csv(csv_text("AF001,2026-11-20,JFK,LHR,2026-11-20T09:00,2026-11-20T17:00,,"))
        with pytest.raises(DomainError) as error:
            executor.execute(db, preview["preview_id"])
        assert error.value.code == "PREVIEW_STALE"
        row = db.execute("SELECT status FROM revocation_previews WHERE preview_id = ?", (preview["preview_id"],)).fetchone()
        assert row["status"] == "STALE"
    finally:
        db.close()
    # A fresh preview after the new import succeeds.
    db = isolated.connect()
    try:
        fresh = create_preview(db, first["batch_id"])
        assert fresh["counts"]["revoke"] == 2
    finally:
        db.close()


def test_interrupted_job_resumes_without_double_revoke(isolated):
    first, _second = _two_batches(isolated)
    db = isolated.connect()
    try:
        preview = create_preview(db, first["batch_id"])
        partial = executor.execute(db, preview["preview_id"], limit=1)
        assert partial["status"] == "RUNNING" and partial["cursor"] == 1
        assert any(item["state"] == "DONE" for item in partial["items"])
        # Old chain still readable while the job is only half applied.
        assert ledger.current_generation(db) == preview["base_generation"]
        resumed = executor.retry(db, partial["job_id"])
        again = executor.retry(db, partial["job_id"])
        current = ledger.active_legs(db)
    finally:
        db.close()
    assert resumed["status"] == "DONE" and again["status"] == "DONE"
    assert [row["business_key"] for row in current] == ["UA857|2026-11-19|SFO|LHR"]
    assert resumed["job_id"] == again["job_id"]


def test_second_execute_after_done_is_idempotent(isolated):
    first, _second = _two_batches(isolated)
    db = isolated.connect()
    try:
        preview = create_preview(db, first["batch_id"])
        first_run = executor.execute(db, preview["preview_id"])
        ledger_before = ledger.active_legs(db)
        second_run = executor.execute(db, preview["preview_id"])
        ledger_after = ledger.active_legs(db)
    finally:
        db.close()
    assert first_run["job_id"] == second_run["job_id"] and first_run["status"] == "DONE"
    assert ledger_before == ledger_after


def test_identical_later_version_does_not_need_adjudication(isolated):
    first = legs_service.import_csv(csv_text(GOOD))
    # Same business key and same content from a different batch id (extra row
    # makes the input bytes differ while the leg content is identical).
    legs_service.import_rows([{**{k: v for k, v in zip(
        ("flight_no", "flight_date", "origin", "destination", "departure_local", "arrival_local"),
        GOOD.split(",")[:6],
    )}}])
    db = isolated.connect()
    try:
        preview = create_preview(db, first["batch_id"])
    finally:
        db.close()
    assert preview["counts"]["adjudicate"] == 0
    assert preview["counts"]["revoke"] + preview["counts"]["retain"] == 1


def test_revoking_twice_is_rejected(isolated):
    first, _second = _two_batches(isolated)
    db = isolated.connect()
    try:
        preview = create_preview(db, first["batch_id"])
        executor.execute(db, preview["preview_id"])
        with pytest.raises(DomainError) as error:
            create_preview(db, first["batch_id"])
        assert error.value.code == "BATCH_ALREADY_REVOKED"
    finally:
        db.close()


def test_old_chain_readable_during_recovery_and_switch_after(isolated):
    first, _second = _two_batches(isolated)
    db = isolated.connect()
    try:
        preview = create_preview(db, first["batch_id"])
        job = executor.execute(db, preview["preview_id"], limit=1)
        assert job["status"] == "RUNNING"
        assert executor.readback(db, job["job_id"])["old_chain_readable"] is True
        assert ledger.current_generation(db) == preview["base_generation"]
        finished = executor.retry(db, job["job_id"])
        assert ledger.current_generation(db) == finished["staging_generation"]
        readback = executor.readback(db, job["job_id"])
    finally:
        db.close()
    assert readback["old_chain_readable"] is False
    assert readback["generation"] == finished["staging_generation"]


def test_revoking_later_batch_restores_earlier_version(isolated):
    source = legs_service.import_csv(csv_text(GOOD))
    later = legs_service.import_csv(csv_text("MU5101,2026-11-16,PVG,JFK,2026-11-16T09:30,2026-11-16T11:00,,"))
    db = isolated.connect()
    try:
        preview = create_preview(db, later["batch_id"])
        assert preview["counts"]["restore"] == 1
        item = preview["items"][0]
        assert item["action"] == "RESTORE"
        job = executor.execute(db, preview["preview_id"])
        readback = executor.readback(db, job["job_id"])
        current = ledger.active_legs(db)
    finally:
        db.close()
    assert job["status"] == "DONE"
    assert readback["restored_legs"][0]["active_leg_id"] != item["source_leg_id"]
    assert len(current) == 1 and current[0]["batch_id"] == source["batch_id"]
    assert readback["conservation"]["accounted"] and readback["conservation"]["balanced"]


def test_new_import_mid_recovery_supersedes_job(isolated):
    first, _second = _two_batches(isolated)
    db = isolated.connect()
    try:
        preview = create_preview(db, first["batch_id"])
        job = executor.execute(db, preview["preview_id"], limit=1)
        legs_service.import_csv(csv_text("AF001,2026-11-20,JFK,LHR,2026-11-20T09:00,2026-11-20T17:00,,"))
        with pytest.raises(DomainError) as error:
            executor.retry(db, job["job_id"])
        assert error.value.code == "PREVIEW_STALE"
        row = db.execute("SELECT status FROM revocation_jobs WHERE job_id = ?", (job["job_id"],)).fetchone()
        assert row["status"] == "SUPERSEDED"
        # The staging generation was never switched in; the import's own
        # generation is current instead.
        assert ledger.current_generation(db) != job["staging_generation"]
        assert ledger.active_legs(db, job["staging_generation"]) != ledger.active_legs(db)
        with pytest.raises(DomainError) as retried:
            executor.retry(db, job["job_id"])
        assert retried.value.code == "JOB_NOT_RUNNABLE"
    finally:
        db.close()


def test_new_preview_refreshes_open_adjudication_candidates(isolated):
    first = legs_service.import_csv(csv_text(GOOD))
    legs_service.import_csv(csv_text("MU5101,2026-11-16,PVG,JFK,2026-11-16T09:30,2026-11-16T11:00,,"))
    db = isolated.connect()
    try:
        first_preview = create_preview(db, first["batch_id"])
        legs_service.import_csv(csv_text("MU5101,2026-11-16,PVG,JFK,2026-11-16T10:00,2026-11-16T11:30,,"))
        second_preview = create_preview(db, first["batch_id"])
        assert second_preview["preview_id"] != first_preview["preview_id"]
        case = adjudicate.list_adjudications(db, first["batch_id"])["items"][0]
        assert case["status"] == "OPEN" and len(case["candidates"]) == 3
        assert case["preview_id"] == second_preview["preview_id"]
    finally:
        db.close()


def test_recompute_connections_after_revocation(isolated):
    first = legs_service.import_csv(csv_text(GOOD))
    db = isolated.connect()
    try:
        preview = create_preview(db, first["batch_id"])
        job = executor.execute(db, preview["preview_id"])
        readback = executor.readback(db, job["job_id"])
    finally:
        db.close()
    chain = readback["chain"]
    assert chain["balanced"] and chain["legs"] == 0
    assert readback["conservation"]["removed_keys"] == ["MU5101|2026-11-16|PVG|JFK"]
