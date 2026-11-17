import pytest
from app.modules.m1_legs.parser import parse_legs, complete_tail
from app.modules.m1_legs.keys import normalize_flight_no, flight_key, keep_external_id

BASE = {"flight_no": "MU5101", "flight_date": "2026-11-16", "origin": "PVG", "destination": "JFK", "departure_local": "2026-11-16T09:00", "arrival_local": "2026-11-16T10:30"}

def test_clean_leg_accepted():
    good, bad = parse_legs([BASE])
    assert len(good) == 1 and not bad and good[0]["origin"] == "PVG"

def test_missing_time_quarantined():
    good, bad = parse_legs([{**BASE, "arrival_local": ""}])
    assert not good and bad[0]["reason_code"] == "EMPTY_VALUE"  # TRAP-05 TRAP-07

def test_exact_duplicate_detected():
    good, bad = parse_legs([BASE, BASE])
    assert len(good) == 1 and bad[0]["reason_code"] == "DUPLICATE_KEY"

def test_conflicting_duplicate_detected():
    good, bad = parse_legs([BASE, {**BASE, "arrival_local": "2026-11-16T11:00"}])
    assert bad[0]["reason_code"] == "VALUE_CONFLICT"  # TRAP-14

def test_flight_no_normalizes():
    assert normalize_flight_no(" mu 5101 ") == "MU5101"

def test_external_id_keeps_large_digits():
    value = "90071992547409931234"
    assert keep_external_id(value) == value  # TRAP-09

def test_truncated_tail_detected():
    assert complete_tail("leg\n") and not complete_tail("leg")  # TRAP-03

