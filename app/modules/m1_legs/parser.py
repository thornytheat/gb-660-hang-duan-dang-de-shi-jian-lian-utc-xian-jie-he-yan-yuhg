REQUIRED = ("flight_no", "flight_date", "origin", "destination", "departure_local", "arrival_local")

def parse_legs(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    accepted, bad, seen = [], [], {}
    for line_no, source in enumerate(rows, 2):
        row = {key: str(value).strip() for key, value in source.items()}
        if any(not row.get(key) for key in REQUIRED):
            bad.append({"line_no": line_no, "reason_code": "EMPTY_VALUE", "raw": source})
            continue
        row["flight_no"] = row["flight_no"].upper(); row["origin"] = row["origin"].upper(); row["destination"] = row["destination"].upper()
        key = (row["flight_no"], row["flight_date"], row["origin"], row["destination"])
        if key in seen:
            code = "DUPLICATE_KEY" if seen[key] == row else "VALUE_CONFLICT"
            bad.append({"line_no": line_no, "reason_code": code, "raw": source}); continue
        seen[key] = dict(row); row["line_no"] = line_no; accepted.append(row)
    return accepted, bad

def complete_tail(text: str) -> bool:
    return not text or text.endswith("\n")

