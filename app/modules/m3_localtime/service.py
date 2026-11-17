from .resolve import resolve_local
from .evidence import offset_evidence

def run(payload: dict | None = None) -> dict:
    payload = payload or {"local": "2026-11-16T09:00", "timezone": "Asia/Shanghai", "fold": None}
    resolved = resolve_local(payload["local"], payload["timezone"], payload.get("fold"))
    return offset_evidence(resolved)

def demo():
    return run()

