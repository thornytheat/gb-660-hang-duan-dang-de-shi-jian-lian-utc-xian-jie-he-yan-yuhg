from .parser import parse_legs
from .keys import flight_key

SAMPLE = [{"flight_no": "mu5101", "flight_date": "2026-11-16", "origin": "pvg", "destination": "jfk", "departure_local": "2026-11-16T09:00", "arrival_local": "2026-11-16T10:30"}]

def run(rows: list[dict] | None = None) -> dict:
    accepted, quarantine = parse_legs(rows or SAMPLE)
    return {"input": len(accepted) + len(quarantine), "accepted": len(accepted), "quarantined": len(quarantine), "keys": [flight_key(row) for row in accepted], "evidence": quarantine}

def demo():
    return run()

