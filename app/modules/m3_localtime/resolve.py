from datetime import datetime, timezone
from zoneinfo import ZoneInfo

def local_candidates(local_value: str, zone_name: str) -> list[datetime]:
    naive = datetime.fromisoformat(local_value)
    zone = ZoneInfo(zone_name)
    result = []
    for fold in (0, 1):
        aware = naive.replace(tzinfo=zone, fold=fold)
        roundtrip = aware.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None)
        if roundtrip == naive and all(existing.utcoffset() != aware.utcoffset() for existing in result):
            result.append(aware)
    return result

def resolve_local(local_value: str, zone_name: str, fold: int | None = None) -> datetime:
    candidates = local_candidates(local_value, zone_name)
    if not candidates:
        raise ValueError("NONEXISTENT_LOCAL_TIME")
    if len(candidates) > 1 and fold is None:
        raise ValueError("AMBIGUOUS_LOCAL_TIME")
    if fold is None:
        return candidates[0]
    selected = [item for item in candidates if item.fold == fold]
    if not selected:
        raise ValueError("BAD_FOLD")
    return selected[0]

def utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

