"""Orchestrates the ingest workload: adapter.load() followed by
adapter.create_indexes(), so ingest throughput and the indexes actually
created are captured together before any read workload runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from graphbench.core.adapter import Adapter, LoadResult


@dataclass(frozen=True, slots=True)
class IngestOutcome:
    load_result: LoadResult
    indexes_created: list[str]


def run_ingest(adapter: Adapter, nodes_csv: Path, edges_csv: Path, batch_size: int) -> IngestOutcome:
    load_result = adapter.load(nodes_csv, edges_csv, batch_size)
    indexes_created = adapter.create_indexes()
    return IngestOutcome(load_result=load_result, indexes_created=indexes_created)
