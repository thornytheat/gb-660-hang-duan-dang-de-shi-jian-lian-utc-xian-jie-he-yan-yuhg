from datetime import timezone
from app.modules.m2_airports.registry import airport_zone
from app.modules.m3_localtime.resolve import resolve_local

def build_leg(row: dict) -> dict:
    departure = resolve_local(row["departure_local"], airport_zone(row["origin"]), row.get("departure_fold"))
    arrival = resolve_local(row["arrival_local"], airport_zone(row["destination"]), row.get("arrival_fold"))
    dep_utc = departure.astimezone(timezone.utc); arr_utc = arrival.astimezone(timezone.utc)
    minutes = int((arr_utc - dep_utc).total_seconds() // 60)
    if minutes <= 0 or minutes > 18 * 60:
        raise ValueError("INVALID_FLIGHT_DURATION")
    return {"flight_no": row["flight_no"], "origin": row["origin"], "destination": row["destination"], "departure_utc": dep_utc.isoformat(), "arrival_utc": arr_utc.isoformat(), "duration_minutes": minutes}

def order_legs(legs: list[dict]) -> list[dict]:
    return sorted(legs, key=lambda row: (row["departure_utc"], row["flight_no"]))

