from .builder import build_leg
from .validate import validate_chain

def run() -> dict:
    leg = build_leg({"flight_no": "MU5101", "origin": "PVG", "destination": "JFK", "departure_local": "2026-11-16T09:00", "arrival_local": "2026-11-16T10:30"})
    return {**leg, "chain_valid": validate_chain([leg])}

def demo():
    return run()

