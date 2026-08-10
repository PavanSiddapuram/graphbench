import pytest

from graphbench.core.record import Record
from graphbench.core.stats import group_by, percentile, summarize, summarize_records


def test_percentile_p50_odd_count() -> None:
    assert percentile([1.0, 2.0, 3.0], 50) == 2.0


def test_percentile_p95_matches_nearest_rank() -> None:
    values = [float(i) for i in range(1, 101)]  # 1..100
    assert percentile(values, 95) == 95.0


def test_percentile_empty_raises() -> None:
    with pytest.raises(ValueError):
        percentile([], 50)


def test_summarize_basic() -> None:
    summary = summarize([10.0, 20.0, 30.0, 40.0])
    assert summary.count == 4
    assert summary.min_ms == 10.0
    assert summary.max_ms == 40.0


def _make_record(platform: str, workload: str, phase: str, ok: bool, latency_ms: float) -> Record:
    return Record(
        run_id="r",
        platform=platform,
        workload=workload,
        phase=phase,
        ok=ok,
        actual_start_ns=0,
        end_ns=int(latency_ms * 1e6),
        latency_ms=latency_ms,
    )


def test_summarize_records_excludes_warmup_and_failures() -> None:
    records = [
        _make_record("cognodb", "hop_1", "warmup", True, 999.0),  # excluded: warmup
        _make_record("cognodb", "hop_1", "measure", False, 999.0),  # excluded: failed
        _make_record("cognodb", "hop_1", "measure", True, 10.0),
        _make_record("cognodb", "hop_1", "measure", True, 20.0),
    ]
    summary = summarize_records(records)
    assert summary.count == 2
    assert summary.max_ms == 20.0


def test_summarize_records_merges_before_percentile_not_after() -> None:
    """Regression guard for CLAUDE.md's 'never average p95s across runs'
    rule: merging two groups of records and summarizing once must not
    equal averaging their independently-computed p95s."""
    group_a = [_make_record("p", "w", "measure", True, v) for v in [1.0, 1.0, 1.0, 100.0]]
    group_b = [_make_record("p", "w", "measure", True, v) for v in [1.0, 1.0, 1.0, 200.0]]

    merged_p95 = summarize_records(group_a + group_b).p95_ms
    averaged_p95 = (summarize_records(group_a).p95_ms + summarize_records(group_b).p95_ms) / 2

    assert merged_p95 != averaged_p95


def test_group_by_multiple_keys() -> None:
    records = [
        _make_record("cognodb", "hop_1", "measure", True, 1.0),
        _make_record("cognodb", "hop_2", "measure", True, 1.0),
        _make_record("neo4j_aura", "hop_1", "measure", True, 1.0),
    ]
    groups = group_by(records, "platform", "workload")
    assert set(groups) == {("cognodb", "hop_1"), ("cognodb", "hop_2"), ("neo4j_aura", "hop_1")}
    assert len(groups[("cognodb", "hop_1")]) == 1
