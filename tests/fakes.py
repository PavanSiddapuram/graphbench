"""FakeAdapter: an in-memory Adapter implementation for tests only.

Per CLAUDE.md's prime-directive corollary, this file must never be
imported from cli.py - tests/test_cli_boundary.py enforces that by
scanning cli.py's source rather than trusting a docstring. Nothing here
returns a synthetic *latency*; timing is real (time.perf_counter_ns()) even
though the "database" underneath is a Python dict, so runner/stats tests
exercise real timing code paths against a graph whose correct query
answers are known in advance.
"""

from __future__ import annotations

import csv
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, ClassVar

from graphbench.core.adapter import ExecuteResult, FootprintResult, LoadResult

QUERIES: dict[str, str] = {
    name: f"FAKE:{name}"
    for name in (
        "hop_1",
        "hop_2",
        "hop_3",
        "point_lookup",
        "filtered_lookup",
        "agg_by_label",
        "insert_edge",
    )
}


class FakeAdapter:
    """An in-memory undirected graph, queried the same way
    adapters/bolt.py's Cypher does: hop_n = exactly n edges away, distinct,
    excluding the start node."""

    QUERIES: ClassVar[dict[str, str]] = QUERIES

    def __init__(self, fail_connect: bool = False, fail_query_names: frozenset[str] = frozenset()) -> None:
        self._fail_connect = fail_connect
        self._fail_query_names = fail_query_names
        self._connected = False
        self._adjacency: dict[str, set[str]] = defaultdict(set)
        self._ml_target: dict[str, str] = {}

    def connect(self) -> None:
        if self._fail_connect:
            raise ConnectionError("FakeAdapter: simulated connect() failure")
        self._connected = True

    def close(self) -> None:
        self._connected = False

    def rtt_probe_ms(self, samples: int = 100) -> list[float]:
        latencies = []
        for _ in range(samples):
            start_ns = time.perf_counter_ns()
            end_ns = time.perf_counter_ns()
            latencies.append((end_ns - start_ns) / 1e6)
        return latencies

    def create_indexes(self) -> list[str]:
        return ["fake index on id", "fake index on ml_target"]

    def load(self, nodes_path: Path, edges_path: Path, batch_size: int) -> LoadResult:
        start_ns = time.perf_counter_ns()
        with nodes_path.open(newline="") as f:
            nodes = list(csv.DictReader(f))
        with edges_path.open(newline="") as f:
            edges = list(csv.DictReader(f))
        for row in nodes:
            self._ml_target[row["id"]] = row.get("ml_target", "")
        for row in edges:
            self._adjacency[row["src"]].add(row["dst"])
            self._adjacency[row["dst"]].add(row["src"])
        end_ns = time.perf_counter_ns()
        wall_clock_ms = (end_ns - start_ns) / 1e6
        wall_clock_s = max(wall_clock_ms / 1000, 1e-9)
        return LoadResult(
            node_count=len(nodes),
            relationship_count=len(edges),
            wall_clock_ms=wall_clock_ms,
            nodes_per_sec=len(nodes) / wall_clock_s,
            relationships_per_sec=len(edges) / wall_clock_s,
        )

    def _neighbors_at_distance(self, start: str, distance: int) -> set[str]:
        frontier = {start}
        visited = {start}
        for _ in range(distance):
            next_frontier: set[str] = set()
            for node in frontier:
                next_frontier |= self._adjacency[node] - visited
            visited |= next_frontier
            frontier = next_frontier
        return frontier - {start}

    def execute(self, query_name: str, params: dict[str, Any]) -> ExecuteResult:
        if query_name in self._fail_query_names:
            raise RuntimeError(f"FakeAdapter: simulated failure for {query_name!r}")

        start_ns = time.perf_counter_ns()
        rows: list[dict[str, Any]]

        if query_name in ("hop_1", "hop_2", "hop_3"):
            distance = int(query_name.split("_")[1])
            rows = [{"id": n} for n in sorted(self._neighbors_at_distance(params["start_id"], distance))]
        elif query_name == "point_lookup":
            node_id = params["start_id"]
            rows = [{"id": node_id, "ml_target": self._ml_target.get(node_id, "")}] if node_id in self._ml_target else []
        elif query_name == "filtered_lookup":
            neighbors = self._neighbors_at_distance(params["start_id"], 1)
            rows = [
                {"id": n} for n in sorted(neighbors) if self._ml_target.get(n) == params["ml_target"]
            ]
        elif query_name == "agg_by_label":
            counts: dict[str, int] = defaultdict(int)
            for label in self._ml_target.values():
                counts[label] += 1
            rows = [{"label": label, "cnt": count} for label, count in sorted(counts.items())]
        elif query_name == "insert_edge":
            self._adjacency[params["src"]].add(params["dst"])
            self._adjacency[params["dst"]].add(params["src"])
            rows = []
        else:
            raise KeyError(f"FakeAdapter has no logical query named {query_name!r}")

        end_ns = time.perf_counter_ns()
        return ExecuteResult(rows=rows, latency_ms=(end_ns - start_ns) / 1e6)

    def footprint(self) -> FootprintResult:
        return FootprintResult(observable=True, stored_bytes=sum(len(v) for v in self._adjacency.values()))
