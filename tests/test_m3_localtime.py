import pytest
from datetime import datetime, timezone
from app.modules.m3_localtime.resolve import local_candidates, resolve_local, utc_iso
from app.modules.m3_localtime.evidence import offset_evidence, same_instant

def test_shanghai_time_unique():
    result = resolve_local("2026-11-16T09:00", "Asia/Shanghai")
    assert result.utcoffset().total_seconds() == 28800

def test_dst_overlap_has_two_candidates():
    assert len(local_candidates("2026-11-01T01:30", "America/New_York")) == 2  # TRAP-12

def test_dst_overlap_requires_fold():
    with pytest.raises(ValueError, match="AMBIGUOUS_LOCAL_TIME"):
        resolve_local("2026-11-01T01:30", "America/New_York")

def test_dst_gap_rejected():
    with pytest.raises(ValueError, match="NONEXISTENT_LOCAL_TIME"):
        resolve_local("2026-03-08T02:30", "America/New_York")

def test_fold_one_selects_later_instant():
    early = resolve_local("2026-11-01T01:30", "America/New_York", 0)
    late = resolve_local("2026-11-01T01:30", "America/New_York", 1)
    assert late.timestamp() - early.timestamp() == 3600

def test_utc_serializes_with_z():
    value = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert utc_iso(value).endswith("Z")  # TRAP-11

def test_offset_evidence_allows_independent_review():
    value = resolve_local("2026-11-16T09:00", "Asia/Shanghai")
    evidence = offset_evidence(value)
    assert evidence["offset"] == "+08:00" and evidence["utc"] == "2026-11-16T01:00:00Z"

