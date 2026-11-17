import pytest
from app.modules.m2_airports.registry import airport_zone, airport_version, AIRPORTS
from app.modules.m2_airports.contracts import normalize_airport, validate_interval, terminal_key

def test_airport_normalizes_uppercase():
    assert normalize_airport(" pvg ") == "PVG"

def test_bad_airport_rejected():
    with pytest.raises(ValueError, match="BAD_AIRPORT"):
        normalize_airport("PV")

def test_airport_has_iana_zone():
    assert airport_zone("JFK") == "America/New_York"

def test_unknown_airport_rejected():
    with pytest.raises(ValueError, match="UNKNOWN_AIRPORT"):
        airport_zone("XXX")

def test_version_uses_half_open_end():
    assert validate_interval("2026-01-01", "2027-01-01")

def test_overlapping_timezone_versions_rejected(monkeypatch):
    monkeypatch.setitem(AIRPORTS, "TST", [("2026-01-01", "2027-01-01", "UTC", "T1"), ("2026-06-01", None, "UTC", "T2")])
    with pytest.raises(ValueError, match="TIMEZONE_VERSION_OVERLAP"):
        airport_version("TST", "2026-07-01")  # TRAP-25

def test_terminal_key_stable():
    assert terminal_key("jfk", " t4 ") == "JFK|T4"

