from fastapi.testclient import TestClient
from app.main import app

def test_all_module_pages_accessible():
    client = TestClient(app)
    for path in ("/legs", "/airports", "/local-time", "/itineraries", "/connections", "/batches"):
        response = client.get(path)
        assert response.status_code == 200 and "panel" in response.text

def test_full_sample_flow_has_utc_chain():
    client = TestClient(app)
    results = [client.post(path).json() for path in ("/api/legs/import", "/api/airports", "/api/local-time/resolve", "/api/itineraries/build", "/api/connections/check", "/api/reconcile")]
    assert results[0]["accepted"] == 1 and results[2]["utc"].endswith("Z") and results[3]["duration_minutes"] == 870 and results[4]["status"] == "VALID"

def test_itinerary_export_downloads():
    response = TestClient(app).get("/api/export/itineraries.csv")
    assert response.status_code == 200 and "MU5101" in response.text

