from datetime import datetime

def waiting_minutes(arrival_utc: datetime, departure_utc: datetime) -> int:
    if arrival_utc.utcoffset() != departure_utc.utcoffset():
        departure_utc = departure_utc.astimezone(arrival_utc.tzinfo)
    return int((departure_utc - arrival_utc).total_seconds() // 60)

def in_half_open(value: datetime, start: datetime, end: datetime) -> bool:
    return start <= value < end

