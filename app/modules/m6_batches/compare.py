def reconcile(input_count: int, valid: int, conflicts: int, quarantined: int) -> dict:
    total = valid + conflicts + quarantined
    return {"input": input_count, "valid": valid, "conflicts": conflicts, "quarantined": quarantined, "balanced": total == input_count, "difference": input_count - total}

def itinerary_account(legs: int, connectable: int, rejected: int) -> dict:
    return {"legs": legs, "connectable": connectable, "rejected": rejected, "balanced": legs == connectable + rejected}

