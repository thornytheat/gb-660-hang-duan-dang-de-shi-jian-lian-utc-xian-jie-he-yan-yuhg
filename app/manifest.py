from hashlib import sha256
from app.config import RULE_VERSION

def input_digest(payload: bytes) -> str:
    return sha256(payload).hexdigest()

def run_id(payload: bytes) -> str:
    return f"{RULE_VERSION}-{input_digest(payload)[:12]}"

def build_manifest(payload: bytes, accepted: int, quarantined: int) -> dict:
    return {"run_id": run_id(payload), "input_sha256": input_digest(payload), "rule_version": RULE_VERSION, "accepted": accepted, "quarantined": quarantined}

