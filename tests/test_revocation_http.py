import pytest
from fastapi.testclient import TestClient

import app.store as store
from app.main import app

HEADER = "flight_no,flight_date,origin,destination,departure_local,arrival_local,departure_fold,arrival_fold\n"
CLEAN = (
    HEADER
    + "MU5101,2026-11-16,PVG,JFK,2026-11-16T09:00,2026-11-16T10:30,,\n"
    + "CA981,2026-11-17,PEK,LHR,2026-11-17T12:00,2026-11-17T20:00,,\n"
)
LATER = HEADER + "UA857,2026-11-19,SFO,LHR,2026-11-19T09:00,2026-11-19T17:00,,\n"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATABASE_PATH", tmp_path / "http.sqlite3")
    store.init_db()
    return TestClient(app)


def post_csv(client, text):
    return client.post("/api/legs/import", content=text, headers={"content-type": "text/csv"})


def test_revocation_page_accessible(client):
    response = client.get("/revocations")
    assert response.status_code == 200 and "批次撤销" in response.text


def test_real_csv_import_reports_line_numbers(client):
    body = CLEAN + "AF001,2026-11-18,JFK,LHR,,2026-11-18T09:00,,\n"
    response = post_csv(client, body)
    assert response.status_code == 200
    data = response.json()
    assert data["accepted"] == 2 and data["quarantined"] == 1
    assert data["evidence"][0]["line_no"] == 4 and data["evidence"][0]["reason_code"] == "EMPTY_VALUE"


def test_full_revocation_flow_via_http(client):
    first = post_csv(client, CLEAN).json()
    post_csv(client, LATER)
    preview = client.post(f"/api/revocations/batches/{first['batch_id']}/preview").json()
    assert preview["counts"]["revoke"] == 2
    job = client.post(f"/api/revocations/previews/{preview['preview_id']}/execute").json()
    assert job["status"] == "DONE"
    readback = client.get(f"/api/revocations/jobs/{job['job_id']}").json()
    assert {row["business_key"] for row in readback["revoked_legs"]} == {
        "MU5101|2026-11-16|PVG|JFK",
        "CA981|2026-11-17|PEK|LHR",
    }
    assert readback["conservation"]["balanced"] and readback["conservation"]["accounted"]
    legs = client.get("/api/revocations/legs").json()
    assert [row["business_key"] for row in legs["items"]] == ["UA857|2026-11-19|SFO|LHR"]


def test_stale_preview_error_shape(client):
    first = post_csv(client, CLEAN).json()
    preview = client.post(f"/api/revocations/batches/{first['batch_id']}/preview").json()
    post_csv(client, LATER)
    response = client.post(f"/api/revocations/previews/{preview['preview_id']}/execute")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "PREVIEW_STALE"


def test_pending_adjudication_blocks_execute_until_resolved(client):
    first = post_csv(client, HEADER + "MU5101,2026-11-16,PVG,JFK,2026-11-16T09:00,2026-11-16T10:30,,\n").json()
    post_csv(client, HEADER + "MU5101,2026-11-16,PVG,JFK,2026-11-16T09:30,2026-11-16T11:00,,\n")
    preview = client.post(f"/api/revocations/batches/{first['batch_id']}/preview").json()
    blocked = client.post(f"/api/revocations/previews/{preview['preview_id']}/execute")
    assert blocked.status_code == 409 and blocked.json()["detail"]["code"] == "CONFLICTS_PENDING"

    cases = client.get(f"/api/revocations/adjudications?batch_id={first['batch_id']}").json()["items"]
    case = cases[0]
    later = [c for c in case["candidates"] if c["batch_id"] != first["batch_id"]][0]
    resolved = client.post(
        f"/api/revocations/adjudications/{case['adjudication_id']}/resolve",
        json={"decision": "KEEP_LATER", "chosen_leg_id": later["leg_id"]},
    )
    assert resolved.status_code == 200 and resolved.json()["status"] == "RESOLVED"
    job = client.post(f"/api/revocations/previews/{preview['preview_id']}/execute").json()
    readback = client.get(f"/api/revocations/jobs/{job['job_id']}").json()
    retained = {row["business_key"]: row for row in readback["retained_legs"]}
    assert retained["MU5101|2026-11-16|PVG|JFK"]["active_leg_id"] == later["leg_id"]


def test_interrupted_execution_resumes_via_retry_endpoint(client):
    first = post_csv(client, CLEAN).json()
    post_csv(client, LATER)
    preview = client.post(f"/api/revocations/batches/{first['batch_id']}/preview").json()
    partial = client.post(
        f"/api/revocations/previews/{preview['preview_id']}/simulate-crash", json={"limit": 1}
    ).json()
    assert partial["status"] == "RUNNING" and partial["cursor"] == 1
    resumed = client.post(f"/api/revocations/jobs/{partial['job_id']}/retry", json={}).json()
    assert resumed["status"] == "DONE"
    again = client.post(f"/api/revocations/jobs/{partial['job_id']}/retry", json={}).json()
    assert again["status"] == "DONE" and again["job_id"] == partial["job_id"]
    readback = client.get(f"/api/revocations/jobs/{partial['job_id']}").json()
    assert len(readback["revoked_legs"]) == 2


def test_sample_page_button_flow_still_works(client):
    response = client.post("/api/legs/import")
    assert response.status_code == 200 and response.json()["accepted"] == 1


def test_legs_page_offers_real_csv_upload(client):
    response = client.get("/legs")
    assert response.status_code == 200 and "/static/m1.js" in response.text


def test_chain_readable_for_base_generation_during_recovery(client):
    first = post_csv(client, CLEAN).json()
    post_csv(client, LATER)
    preview = client.post(f"/api/revocations/batches/{first['batch_id']}/preview").json()
    partial = client.post(
        f"/api/revocations/previews/{preview['preview_id']}/simulate-crash", json={"limit": 1}
    ).json()
    assert partial["status"] == "RUNNING"
    old = client.get(f"/api/revocations/chain?generation={preview['base_generation']}").json()
    current = client.get("/api/revocations/chain").json()
    assert old["generation"] == preview["base_generation"]
    assert old["chain"]["legs"] == 3
    assert current["generation"] == preview["base_generation"]
    assert current["chain"]["legs"] == 3


def test_missing_batch_preview_returns_404(client):
    response = client.post("/api/revocations/batches/nope/preview")
    assert response.status_code == 404 and response.json()["detail"]["code"] == "BATCH_NOT_FOUND"
