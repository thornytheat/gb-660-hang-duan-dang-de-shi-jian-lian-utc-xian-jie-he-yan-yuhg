from datetime import datetime
from .rules import required_minutes, connection_result
from .windows import waiting_minutes

def run(payload: dict | None = None) -> dict:
    payload = payload or {"arrival_utc": "2026-11-16T10:00:00+00:00", "departure_utc": "2026-11-16T12:30:00+00:00", "airport": "JFK", "arrival_terminal": "T4", "departure_terminal": "T1"}
    wait = waiting_minutes(datetime.fromisoformat(payload["arrival_utc"]), datetime.fromisoformat(payload["departure_utc"]))
    required = required_minutes(payload["airport"], payload["arrival_terminal"], payload["departure_terminal"])
    return connection_result(wait, required, 720)

def demo():
    return run()

