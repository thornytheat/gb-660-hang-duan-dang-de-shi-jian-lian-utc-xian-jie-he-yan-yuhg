import csv
import io

from .keys import normalize_flight_no

REQUIRED = ("flight_no", "flight_date", "origin", "destination", "departure_local", "arrival_local")


def _clean_value(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_leg(source: dict) -> dict:
    """Canonical leg shape shared by every importer.

    Folds are always present (``None`` when absent) and no extra source columns
    leak in, so the same leg content hashes identically whether it arrived as
    CSV with empty fold columns or as JSON without fold keys.
    """
    return {
        "flight_no": str(source.get("flight_no", "")).strip().upper(),
        "flight_date": str(source.get("flight_date", "")).strip(),
        "origin": str(source.get("origin", "")).strip().upper(),
        "destination": str(source.get("destination", "")).strip().upper(),
        "departure_local": str(source.get("departure_local", "")).strip(),
        "arrival_local": str(source.get("arrival_local", "")).strip(),
        "departure_fold": _fold(source.get("departure_fold")),
        "arrival_fold": _fold(source.get("arrival_fold")),
    }


def _fold(value) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    if text not in ("0", "1"):
        raise ValueError("BAD_FOLD")
    return int(text)


def parse_leg_pairs(pairs) -> tuple[list[dict], list[dict]]:
    """Parse ``(physical_line_no, row)`` pairs into accepted rows and evidence.

    Line numbers are supplied by the caller so CSV, JSON and file imports all
    report the physical source line instead of a positional index.
    """
    accepted, bad, seen = [], [], {}
    for line_no, source in pairs:
        try:
            row = normalize_leg(source)
        except ValueError:
            bad.append({"line_no": line_no, "reason_code": "BAD_FOLD", "raw": source})
            continue
        if any(not row.get(key) for key in REQUIRED):
            bad.append({"line_no": line_no, "reason_code": "EMPTY_VALUE", "raw": source})
            continue
        try:
            row["flight_no"] = normalize_flight_no(row["flight_no"])
        except ValueError:
            bad.append({"line_no": line_no, "reason_code": "BAD_FLIGHT_NO", "raw": source})
            continue
        key = (row["flight_no"], row["flight_date"], row["origin"], row["destination"])
        if key in seen:
            code = "DUPLICATE_KEY" if seen[key] == row else "VALUE_CONFLICT"
            bad.append({"line_no": line_no, "reason_code": code, "raw": source})
            continue
        seen[key] = dict(row)
        row["line_no"] = line_no
        accepted.append(row)
    return accepted, bad


def parse_legs(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    return parse_leg_pairs(enumerate(rows, 2))


def parse_csv_legs(text: str) -> tuple[list[dict], list[dict]]:
    """Parse CSV text, reporting physical line numbers.

    A truncated final line is quarantined with ``TRUNCATED_TAIL`` instead of
    leaking a half record into the accepted set (TRAP-03).
    """
    tail_evidence = []
    if text and not complete_tail(text):
        lines = text.split("\n")
        tail_evidence.append(
            {"line_no": len(lines), "reason_code": "TRUNCATED_TAIL", "raw": {"text": lines[-1]}}
        )
        text = text[: text.rfind("\n") + 1]
    # A UTF-8 BOM would otherwise become part of the first header name.
    reader = csv.reader(io.StringIO(text.lstrip("﻿")))
    try:
        header = [item.strip() for item in next(reader)]
    except StopIteration:
        raise ValueError("EMPTY_INPUT")
    missing = [key for key in REQUIRED if key not in header]
    if missing:
        raise ValueError("BAD_HEADER")
    pairs = []
    for values in reader:
        line_no = reader.line_num
        if not values or all(not _clean_value(value) for value in values):
            continue
        row = {name: (values[index] if index < len(values) else "") for index, name in enumerate(header)}
        pairs.append((line_no, row))
    accepted, bad = parse_leg_pairs(pairs)
    return accepted, tail_evidence + bad


def complete_tail(text: str) -> bool:
    return not text or text.endswith("\n")
