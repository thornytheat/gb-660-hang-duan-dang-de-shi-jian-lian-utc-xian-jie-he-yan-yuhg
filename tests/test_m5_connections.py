import pytest
from datetime import datetime, timezone
from app.modules.m5_connections.rules import required_minutes, connection_result
from app.modules.m5_connections.windows import waiting_minutes, in_half_open

def test_terminal_change_adds_buffer():
    assert required_minutes("JFK", "T4", "T1") == 120

def test_same_terminal_uses_base():
    assert required_minutes("JFK", "T4", "T4") == 90

def test_unknown_airport_rejected():
    with pytest.raises(ValueError, match="UNKNOWN_AIRPORT"):
        required_minutes("XXX", "A", "B")

def test_short_connection_rejected():
    assert connection_result(80, 90, 720)["status"] == "TOO_SHORT"

def test_negative_wait_is_overlap():
    assert connection_result(-1, 90, 720)["status"] == "OVERLAP"

def test_wait_minutes_exact():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc); end = datetime(2026, 1, 1, 2, 30, tzinfo=timezone.utc)
    assert waiting_minutes(start, end) == 150

def test_half_open_window_excludes_end():
    start = datetime(2026, 1, 1); end = datetime(2026, 1, 2)
    assert in_half_open(start, start, end) and not in_half_open(end, start, end)  # TRAP-23

