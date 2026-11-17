from datetime import date

AIRPORTS = {
    "PVG": [("2000-01-01", None, "Asia/Shanghai", "T1")],
    "JFK": [("2000-01-01", None, "America/New_York", "T4")],
    "LHR": [("2000-01-01", None, "Europe/London", "T5")],
    "SFO": [("2000-01-01", None, "America/Los_Angeles", "I")],
}

def airport_version(code: str, at: str) -> dict:
    target = date.fromisoformat(at)
    matches = [item for item in AIRPORTS.get(code, []) if date.fromisoformat(item[0]) <= target and (item[1] is None or target < date.fromisoformat(item[1]))]
    if not matches:
        raise ValueError("UNKNOWN_AIRPORT")
    if len(matches) > 1:
        raise ValueError("TIMEZONE_VERSION_OVERLAP")
    start, end, zone, terminal = matches[0]
    return {"start": start, "end": end, "timezone": zone, "terminal": terminal}

def airport_zone(code: str, at: str = "2026-11-16") -> str:
    return airport_version(code, at)["timezone"]

