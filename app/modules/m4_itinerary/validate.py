from datetime import datetime

def validate_chain(legs: list[dict]) -> bool:
    for index, leg in enumerate(legs):
        if datetime.fromisoformat(leg["arrival_utc"]) <= datetime.fromisoformat(leg["departure_utc"]):
            return False
        if index and legs[index - 1]["destination"] != leg["origin"]:
            return False
    return True

def chain_span_minutes(legs: list[dict]) -> int:
    if not legs:
        return 0
    return int((datetime.fromisoformat(legs[-1]["arrival_utc"]) - datetime.fromisoformat(legs[0]["departure_utc"])).total_seconds() // 60)

