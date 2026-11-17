BASE_MINUTES = {"JFK": 90, "LHR": 75, "PVG": 60, "SFO": 80}

def required_minutes(airport: str, arrival_terminal: str, departure_terminal: str) -> int:
    if airport not in BASE_MINUTES:
        raise ValueError("UNKNOWN_AIRPORT")
    transfer = 30 if arrival_terminal != departure_terminal else 0
    return BASE_MINUTES[airport] + transfer

def connection_result(wait: int, required: int, maximum: int) -> dict:
    if wait < 0:
        return {"status": "OVERLAP", "wait_minutes": wait, "required_minutes": required}
    if wait < required:
        return {"status": "TOO_SHORT", "wait_minutes": wait, "required_minutes": required}
    if wait > maximum:
        return {"status": "TOO_LONG", "wait_minutes": wait, "required_minutes": required}
    return {"status": "VALID", "wait_minutes": wait, "required_minutes": required}

