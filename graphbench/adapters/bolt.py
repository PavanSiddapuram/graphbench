"""Bolt+Cypher adapter, shared by every platform that speaks the official
Neo4j wire protocol: CognoDB Cloud, Neo4j AuraDB Free and Memgraph Cloud.
Per CLAUDE.md's "adding a platform" rule, none of those three needed a new
adapter file - only a new block in config/platforms.yaml pointing `adapter:
bolt` at different connection env vars.

Nodes are stored as a single :Developer label with an `id` and `ml_target`
property (see graphbench/dataset/manifest.py); the single relationship
type is :FOLLOWS, created directed but queried with an undirected pattern
(`-[:FOLLOWS]-`) since the source dataset is a mutual-follower network.
"""

from __future__ import annotations

import csv
import time
from pathlib import Path
from typing import Any, ClassVar

from neo4j import Driver, GraphDatabase

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
    "insert_edge": (
        "MATCH (a:Developer {id: $src}), (b:Developer {id: $dst}) MERGE (a)-[:FOLLOWS]->(b)"
    ),
}


class BoltAdapter:
    QUERIES: ClassVar[dict[str, str]] = QUERIES

    def __init__(self, uri: str, user: str, password: str, database: str | None = None) -> None:
        self._uri = uri
        self._user = user
        self._password = password
        self._database = database
        self._driver: Driver | None = None

    def connect(self) -> None:
        self._driver = GraphDatabase.driver(self._uri, auth=(self._user, self._password))
        self._driver.verify_connectivity()

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()
            self._driver = None

    @property
    def _require_driver(self) -> Driver:
        if self._driver is None:
            raise RuntimeError("connect() must be called before using this adapter")
        return self._driver

    def rtt_probe_ms(self, samples: int = 100) -> list[float]:
        latencies: list[float] = []
        with self._require_driver.session(database=self._database) as session:
            for _ in range(samples):
                start_ns = time.perf_counter_ns()
                session.run("RETURN 1").consume()
                end_ns = time.perf_counter_ns()
                latencies.append((end_ns - start_ns) / 1e6)
        return latencies

    def create_indexes(self) -> list[str]:
        statements = [
            (
                "CREATE CONSTRAINT developer_id_unique IF NOT EXISTS "
                "FOR (n:Developer) REQUIRE n.id IS UNIQUE"
            ),
            "CREATE INDEX developer_ml_target IF NOT EXISTS FOR (n:Developer) ON (n.ml_target)",
        ]
        with self._require_driver.session(database=self._database) as session:
            for statement in statements:
                session.run(statement).consume()
        return statements

    def load(self, nodes_path: Path, edges_path: Path, batch_size: int) -> LoadResult:
        with nodes_path.open(newline="") as f:
            nodes = list(csv.DictReader(f))
        with edges_path.open(newline="") as f:
            edges = list(csv.DictReader(f))

        start_ns = time.perf_counter_ns()
        with self._require_driver.session(database=self._database) as session:
            for batch in _chunks(nodes, batch_size):
                session.run(
                    "UNWIND $rows AS row "
                    "MERGE (n:Developer {id: row.id}) SET n.ml_target = row.ml_target",
                    rows=batch,
                ).consume()
            for batch in _chunks(edges, batch_size):
                session.run(
                    "UNWIND $rows AS row "
                    "MATCH (a:Developer {id: row.src}), (b:Developer {id: row.dst}) "
                    "MERGE (a)-[:FOLLOWS]->(b)",
                    rows=batch,
                ).consume()
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
        start_ns = time.perf_counter_ns()
        with self._require_driver.session(database=self._database) as session:
            result = session.run(query, **params)
            rows = [dict(record) for record in result]
        end_ns = time.perf_counter_ns()
        return ExecuteResult(rows=rows, latency_ms=(end_ns - start_ns) / 1e6)

    def footprint(self) -> FootprintResult:
        try:
            with self._require_driver.session(database=self._database) as session:
                record = session.run(
                    "CALL apoc.monitor.store() YIELD stringStoreSize RETURN stringStoreSize"
                ).single()
            if record is None:
                raise RuntimeError("apoc.monitor.store() returned no rows")
            return FootprintResult(observable=True, stored_bytes=int(record["stringStoreSize"]))
        except Exception as exc:  # noqa: BLE001 - footprint is best-effort per platform
            return FootprintResult(
                observable=False,
                note=f"store size not observable over Bolt without APOC: {exc!r}",
            )


def _chunks(rows: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [rows[i : i + size] for i in range(0, len(rows), size)]
