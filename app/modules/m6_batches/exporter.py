import csv
import io

def itineraries_csv(rows: list[dict]) -> str:
    output = io.StringIO(newline="")
    fields = ["flight_key", "departure_utc", "arrival_utc", "status", "reason_code"]
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader(); writer.writerows(rows)
    return output.getvalue()

