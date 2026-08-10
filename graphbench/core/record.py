"""The Record dataclass is the only thing that ever gets appended to
results/raw/<run_id>.jsonl. Every field here is either measured directly
(via time.perf_counter_ns()) or a label describing the measurement - never
a derived summary statistic. Aggregation happens only in analysis/.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

Phase = Literal["warmup", "measure"]
DegreeBand = Literal["low", "mid", "high"]


@dataclass(slots=True)
class Record:
    run_id: str
    platform: str
    workload: str
    phase: Phase
    ok: bool

    # perf_counter_ns() readings - monotonic, only meaningful as deltas
    # within this process. wall_clock_iso below is for human log-reading
    # only and must never be used to compute a duration.
    actual_start_ns: int
    end_ns: int
    latency_ms: float

    wall_clock_iso: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    # open-loop scheduling (core/runner.py); None for closed-loop calls
    # such as load() or the equality gate.
    intended_start_ns: int | None = None
    queue_delay_ms: float | None = None

    # sampling / workload context
    degree_band: DegreeBand | None = None
    start_node_id: str | None = None
    concurrency: int | None = None
    rows_returned: int | None = None
    fingerprint: str | None = None

    # ingest workload only: raw counts, so analysis/ derives nodes_per_sec
    # and relationships_per_sec from latency_ms instead of this Record
    # carrying a precomputed rate.
    node_count: int | None = None
    relationship_count: int | None = None

    error: str | None = None

    def to_jsonl(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))

    @staticmethod
    def from_jsonl(line: str) -> Record:
        data: dict[str, Any] = json.loads(line)
        return Record(**data)
