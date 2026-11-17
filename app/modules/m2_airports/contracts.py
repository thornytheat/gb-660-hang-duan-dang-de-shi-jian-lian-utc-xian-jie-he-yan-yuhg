import re

def normalize_airport(value: str) -> str:
    token = value.strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", token):
        raise ValueError("BAD_AIRPORT")
    return token

def validate_interval(start: str, end: str | None) -> bool:
    return end is None or start < end

def terminal_key(airport: str, terminal: str) -> str:
    return f"{normalize_airport(airport)}|{terminal.strip().upper()}"

