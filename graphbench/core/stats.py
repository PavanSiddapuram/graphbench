"""Percentiles from merged raw samples. Never average p95s across runs:
merge every matching Record's latency_ms first, then take one percentile
of the merged set. Never compute percentiles from pre-bucketed data.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from graphbench.core.record import Record


@dataclass(frozen=True, slots=True)
class PercentileSummary:
    count: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    min_ms: float
    max_ms: float


def percentile(values: list[float], p: float) -> float:
    """Nearest-rank percentile over `values`, p in [0, 100]."""
    if not values:
        raise ValueError("cannot take a percentile of zero samples")
    ordered = sorted(values)
    rank = math.ceil(p / 100 * len(ordered)) - 1
    rank = min(max(rank, 0), len(ordered) - 1)
    return ordered[rank]


def summarize(latencies_ms: list[float]) -> PercentileSummary:
    if not latencies_ms:
        raise ValueError("cannot summarize zero samples")
    return PercentileSummary(
        count=len(latencies_ms),
        p50_ms=percentile(latencies_ms, 50),
        p95_ms=percentile(latencies_ms, 95),
        p99_ms=percentile(latencies_ms, 99),
        min_ms=min(latencies_ms),
        max_ms=max(latencies_ms),
    )


def summarize_records(records: list[Record], phase: str = "measure") -> PercentileSummary:
    """Merges latency_ms from every matching, successful Record before
    taking percentiles. Callers must pre-filter `records` to one
    (platform, workload, degree_band) group with group_by() - mixing
    groups here would produce a meaningless summary."""
    latencies = [r.latency_ms for r in records if r.phase == phase and r.ok]
    return summarize(latencies)


def group_by(records: list[Record], *keys: str) -> dict[tuple[str, ...], list[Record]]:
    """Groups records by Record field names, e.g.
    group_by(records, "platform", "workload", "degree_band")."""
    groups: dict[tuple[str, ...], list[Record]] = {}
    for record in records:
        group_key = tuple(str(getattr(record, key)) for key in keys)
        groups.setdefault(group_key, []).append(record)
    return groups
