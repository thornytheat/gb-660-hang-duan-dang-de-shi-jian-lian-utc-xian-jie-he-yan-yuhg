import re

def normalize_flight_no(value: str) -> str:
    token = value.strip().upper().replace(" ", "")
    if not re.fullmatch(r"[A-Z0-9]{2,3}\d{1,4}", token):
        raise ValueError("BAD_FLIGHT_NO")
    return token

def flight_key(row: dict) -> str:
    return "|".join((normalize_flight_no(row["flight_no"]), row["flight_date"], row["origin"], row["destination"]))

def keep_external_id(value: str) -> str:
    return str(value).strip()

