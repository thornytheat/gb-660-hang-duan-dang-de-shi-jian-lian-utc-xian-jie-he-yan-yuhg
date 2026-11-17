import pytest
from app.modules.m4_itinerary.builder import build_leg, order_legs
from app.modules.m4_itinerary.validate import validate_chain, chain_span_minutes

BASE = {"flight_no": "MU5101", "origin": "PVG", "destination": "JFK", "departure_local": "2026-11-16T09:00", "arrival_local": "2026-11-16T10:30"}

def test_leg_duration_uses_utc_not_wall_clock():
    leg = build_leg(BASE)
    assert leg["duration_minutes"] == 870

def test_arrival_before_departure_rejected():
    with pytest.raises(ValueError, match="INVALID_FLIGHT_DURATION"):
        build_leg({**BASE, "arrival_local": "2026-11-15T10:30"})

def test_unrealistic_duration_rejected():
    with pytest.raises(ValueError, match="INVALID_FLIGHT_DURATION"):
        build_leg({**BASE, "arrival_local": "2026-11-17T10:30"})

def test_order_by_utc_is_stable():
    rows = [{"flight_no": "B", "departure_utc": "2026-01-01T02:00:00+00:00"}, {"flight_no": "A", "departure_utc": "2026-01-01T01:00:00+00:00"}]
    assert [row["flight_no"] for row in order_legs(rows)] == ["A", "B"]  # TRAP-13

def test_valid_chain_requires_airport_continuity():
    first = {"origin": "A", "destination": "B", "departure_utc": "2026-01-01T00:00:00+00:00", "arrival_utc": "2026-01-01T01:00:00+00:00"}
    second = {"origin": "C", "destination": "D", "departure_utc": "2026-01-01T02:00:00+00:00", "arrival_utc": "2026-01-01T03:00:00+00:00"}
    assert not validate_chain([first, second])

def test_single_leg_chain_valid():
    assert validate_chain([build_leg(BASE)])

def test_empty_chain_span_zero():
    assert chain_span_minutes([]) == 0

