from datetime import datetime
from .resolve import utc_iso

def offset_evidence(value: datetime) -> dict:
    offset = value.utcoffset()
    minutes = int(offset.total_seconds() // 60) if offset else 0
    sign = "+" if minutes >= 0 else "-"
    absolute = abs(minutes)
    return {"local": value.replace(tzinfo=None).isoformat(), "timezone": str(value.tzinfo), "fold": value.fold, "offset": f"{sign}{absolute // 60:02d}:{absolute % 60:02d}", "utc": utc_iso(value)}

def same_instant(left: datetime, right: datetime) -> bool:
    return left.timestamp() == right.timestamp()

