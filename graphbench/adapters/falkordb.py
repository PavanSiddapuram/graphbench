"""FalkorDB adapter. FalkorDB speaks a Cypher subset over the Redis (RESP)
protocol via the official `falkordb` Python client (confirmed against
falkordb==1.6.2, the version pinned in requirements.txt: `FalkorDB(host,
port, password)`, `.select_graph(name).query(cypher, params=...)`, index/
constraint creation via dedicated methods rather than `CREATE INDEX`
statements).

QUERIES mirrors adapters/bolt.py's Cypher text exactly - FalkorDB's Cypher
subset covers everything these workloads use - so the "same logical
queries" claim in CLAUDE.md holds across both.

NOTE: this adapter has been checked against the installed `falkordb`
client's real method signatures, but has never been run against a live
FalkorDB server (see CLAUDE.md's "Known environment constraint" and
results/failures.md). Re-verify QueryResult.header/.result_set parsing
against a real server before trusting its output.
"""

from __future__ import annotations

import csv
import time
from pathlib import Path
from typing import Any, ClassVar

from falkordb import FalkorDB
from falkordb.graph import Graph

from graphbench.core.adapter import ExecuteResult, FootprintResult, LoadResult

QUERIES: dict[str, str] = {
    "hop_1": "MATCH (n:Developer {id: $start_id})-[:FOLLOWS]-(m:Developer) RETURN DISTINCT m.id AS id",
    "hop_2": (
        "MATCH (n:Developer {id: $start_id})-[:FOLLOWS*2]-(m:Developer) "
        "WHERE m.id <> $start_id RETURN DISTINCT m.id AS id"
    ),
    "hop_3": (
        "MATCH (n:Developer {id: $start_id})-[:FOLLOWS*3]-(m:Developer) "
        "WHERE m.id <> $start_id RETURN DISTINCT m.id AS id"
    ),
    "point_lookup": "MATCH (n:Developer {id: $start_id}) RETURN n.id AS id, n.ml_target AS ml_target",
    "filtered_lookup": (
        "MATCH (n:Developer {id: $start_id})-[:FOLLOWS]-(m:Developer) "
        "WHERE m.ml_target = $ml_target RETURN DISTINCT m.id AS id"
    ),
    "agg_by_label": "MATCH (n:Developer) RETURN n.ml_target AS label, count(*) AS cnt ORDER BY label",
    "insert_edge": "MATCH (a:Developer {id: $src}), (b:Developer {id: $dst}) MERGE (a)-[:FOLLOWS]->(b)",
}


class FalkorDBAdapter:
    QUERIES: ClassVar[dict[str, str]] = QUERIES

    def __init__(self, host: str, port: int, password: str | None, graph_name: str) -> None:
        self._host = host
        self._port = port
        self._password = password
        self._graph_name = graph_name
        self._db: FalkorDB | None = None

    def connect(self) -> None:
        self._db = FalkorDB(host=self._host, port=self._port, password=self._password)

    def close(self) -> None:
        # the falkordb client pools RESP connections internally and has no
        # explicit close(); dropping the reference is the documented way
        # to release it.
        self._db = None

    @property
    def _graph(self) -> Graph:
        if self._db is None:
            raise RuntimeError("connect() must be called before using this adapter")
        return self._db.select_graph(self._graph_name)

    def rtt_probe_ms(self, samples: int = 100) -> list[float]:
        graph = self._graph
        latencies: list[float] = []
        for _ in range(samples):
            start_ns = time.perf_counter_ns()
            graph.query("RETURN 1")
            end_ns = time.perf_counter_ns()
            latencies.append((end_ns - start_ns) / 1e6)
        return latencies

    def create_indexes(self) -> list[str]:
        graph = self._graph
        created: list[str] = []
        try:
            graph.create_node_unique_constraint("Developer", "id")
            created.append("unique constraint Developer.id")
        except Exception as exc:  # noqa: BLE001 - already-exists is not a hard failure
            created.append(f"unique constraint Developer.id: skipped ({exc!r})")
        try:
            graph.create_node_range_index("Developer", "ml_target")
            created.append("range index Developer.ml_target")
        except Exception as exc:  # noqa: BLE001
            created.append(f"range index Developer.ml_target: skipped ({exc!r})")
        return created

    def load(self, nodes_path: Path, edges_path: Path, batch_size: int) -> LoadResult:
        with nodes_path.open(newline="") as f:
            nodes = list(csv.DictReader(f))
        with edges_path.open(newline="") as f:
            edges = list(csv.DictReader(f))

        graph = self._graph
        start_ns = time.perf_counter_ns()
        for batch in _chunks(nodes, batch_size):
            graph.query(
                "UNWIND $rows AS row MERGE (n:Developer {id: row.id}) SET n.ml_target = row.ml_target",
                params={"rows": batch},
            )
        for batch in _chunks(edges, batch_size):
            graph.query(
                "UNWIND $rows AS row "
                "MATCH (a:Developer {id: row.src}), (b:Developer {id: row.dst}) "
                "MERGE (a)-[:FOLLOWS]->(b)",
                params={"rows": batch},
            )
        end_ns = time.perf_counter_ns()

        wall_clock_ms = (end_ns - start_ns) / 1e6
        wall_clock_s = wall_clock_ms / 1000
        return LoadResult(
            node_count=len(nodes),
            relationship_count=len(edges),
            wall_clock_ms=wall_clock_ms,
            nodes_per_sec=len(nodes) / wall_clock_s if wall_clock_s > 0 else 0.0,
            relationships_per_sec=len(edges) / wall_clock_s if wall_clock_s > 0 else 0.0,
        )

    def execute(self, query_name: str, params: dict[str, Any]) -> ExecuteResult:
        query = self.QUERIES[query_name]
        graph = self._graph
        start_ns = time.perf_counter_ns()
        result = graph.query(query, params=params)
        end_ns = time.perf_counter_ns()

        column_names = [column[1] for column in result.header] if result.header else []
        rows = [dict(zip(column_names, row, strict=True)) for row in result.result_set]
        return ExecuteResult(rows=rows, latency_ms=(end_ns - start_ns) / 1e6)

    def footprint(self) -> FootprintResult:
        try:
            info = self._graph.list_indices()  # confirms connectivity/introspection is possible at all
            return FootprintResult(
                observable=False,
                note=f"FalkorDB free tier exposes no memory/storage size API; indices={info!r}",
            )
        except Exception as exc:  # noqa: BLE001 - footprint is best-effort per platform
            return FootprintResult(observable=False, note=f"footprint introspection failed: {exc!r}")


def _chunks(rows: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [rows[i : i + size] for i in range(0, len(rows), size)]
