"""ArangoDB Oasis adapter - the deliberately non-Cypher platform (AQL),
per assignment section 4. Uses the official `python-arango` client
(confirmed against python-arango==8.3.3, the version pinned in
requirements.txt: `ArangoClient(hosts=...)`, `client.db(name, username,
password, verify=...)`, `db.aql.execute(query, bind_vars=...)`,
`collection.insert_many(docs)`, `collection.add_persistent_index(fields=...)`).

Vertices live in the `developers` collection, edges in `follows`
(`_from`/`_to` referencing `developers/<id>`). QUERIES below is AQL, not a
Cypher translation with the serial numbers filed off - graph traversal
syntax (`FOR v IN n..m ANY start edge_collection`) differs enough from
Cypher's variable-length pattern matching that hop_2/hop_3 result sets are
NOT guaranteed to agree node-for-node with adapters/bolt.py's `[:FOLLOWS*n]`
in a graph with cycles or shared neighbors (AQL's traversal here uses
uniqueVertices: 'global', Cypher's variable-length match does not
dedupe intermediate nodes the same way). This is exactly the kind of
divergence core/validate.py's equality gate exists to catch - see
results/failures.md and the README's threats-to-validity table; do not
loosen the fingerprint comparison to paper over a real mismatch here.

NOTE: checked against the installed `python-arango` client's real method
signatures, but never run against a live ArangoDB Oasis instance (see
CLAUDE.md's "Known environment constraint").
"""

from __future__ import annotations

import csv
import time
from pathlib import Path
from typing import Any, ClassVar, cast

from arango.client import ArangoClient
from arango.cursor import Cursor
from arango.database import StandardDatabase

from graphbench.core.adapter import ExecuteResult, FootprintResult, LoadResult

VERTEX_COLLECTION = "developers"
EDGE_COLLECTION = "follows"

QUERIES: dict[str, str] = {
    # every query projects to {id: ...} (or {id, ml_target}/{label, cnt}) so
    # the JSON shape returned to core/validate.py's fingerprint matches
    # adapters/bolt.py's and adapters/falkordb.py's `RETURN ... AS id`
    # column naming exactly, even though AQL has no `AS` for RETURN.
    "hop_1": f"FOR v IN 1..1 ANY @start_id {EDGE_COLLECTION} RETURN DISTINCT {{id: v._key}}",
    "hop_2": (
        f"FOR v IN 2..2 ANY @start_id {EDGE_COLLECTION} "
        "OPTIONS {bfs: true, uniqueVertices: 'global'} "
        "FILTER v._key != @start_key RETURN DISTINCT {id: v._key}"
    ),
    "hop_3": (
        f"FOR v IN 3..3 ANY @start_id {EDGE_COLLECTION} "
        "OPTIONS {bfs: true, uniqueVertices: 'global'} "
        "FILTER v._key != @start_key RETURN DISTINCT {id: v._key}"
    ),
    "point_lookup": (
        f"FOR d IN {VERTEX_COLLECTION} FILTER d._key == @start_key "
        "RETURN {id: d._key, ml_target: d.ml_target}"
    ),
    "filtered_lookup": (
        f"FOR v IN 1..1 ANY @start_id {EDGE_COLLECTION} "
        "FILTER v.ml_target == @ml_target RETURN DISTINCT {id: v._key}"
    ),
    "agg_by_label": (
        f"FOR d IN {VERTEX_COLLECTION} COLLECT label = d.ml_target WITH COUNT INTO cnt "
        "SORT label RETURN {label: label, cnt: cnt}"
    ),
    "insert_edge": f"INSERT {{_from: @src_id, _to: @dst_id}} INTO {EDGE_COLLECTION}",
}


class ArangoDBAdapter:
    QUERIES: ClassVar[dict[str, str]] = QUERIES

    def __init__(self, url: str, user: str, password: str, database: str) -> None:
        self._url = url
        self._user = user
        self._password = password
        self._database = database
        self._db: StandardDatabase | None = None

    def connect(self) -> None:
        client = ArangoClient(hosts=self._url)
        self._db = client.db(self._database, username=self._user, password=self._password, verify=True)

    def close(self) -> None:
        self._db = None  # python-arango has no persistent socket to close; HTTP connections are per-request

    @property
    def _require_db(self) -> StandardDatabase:
        if self._db is None:
            raise RuntimeError("connect() must be called before using this adapter")
        return self._db

    def rtt_probe_ms(self, samples: int = 100) -> list[float]:
        db = self._require_db
        latencies: list[float] = []
        for _ in range(samples):
            start_ns = time.perf_counter_ns()
            # db.aql.execute() is typed to also cover async_req/batch job
            # wrappers; this adapter never sets those, so the return is
            # always a plain Cursor - see the same cast in execute() below.
            list(cast(Cursor, db.aql.execute("RETURN 1")))
            end_ns = time.perf_counter_ns()
            latencies.append((end_ns - start_ns) / 1e6)
        return latencies

    def _ensure_collections(self) -> None:
        db = self._require_db
        if not db.has_collection(VERTEX_COLLECTION):
            db.create_collection(VERTEX_COLLECTION)
        if not db.has_collection(EDGE_COLLECTION):
            db.create_collection(EDGE_COLLECTION, edge=True)

    def create_indexes(self) -> list[str]:
        self._ensure_collections()
        # _key is already unique-indexed by ArangoDB for every collection,
        # so point_lookup needs no extra index; ml_target does. Idempotent:
        # a rerun against an already-indexed collection is not a failure.
        try:
            self._require_db.collection(VERTEX_COLLECTION).add_persistent_index(fields=["ml_target"])
            created = f"persistent index {VERTEX_COLLECTION}.ml_target"
        except Exception as exc:  # noqa: BLE001 - already-exists is not a hard failure
            created = f"persistent index {VERTEX_COLLECTION}.ml_target: skipped ({exc!r})"
        return [f"{VERTEX_COLLECTION}._key: implicit primary index", created]

    def load(self, nodes_path: Path, edges_path: Path, batch_size: int) -> LoadResult:
        db = self._require_db
        self._ensure_collections()

        with nodes_path.open(newline="") as f:
            nodes = list(csv.DictReader(f))
        with edges_path.open(newline="") as f:
            edges = list(csv.DictReader(f))

        vertex_collection = db.collection(VERTEX_COLLECTION)
        edge_collection = db.collection(EDGE_COLLECTION)

        start_ns = time.perf_counter_ns()
        for batch in _chunks(nodes, batch_size):
            documents = [{"_key": row["id"], "ml_target": row["ml_target"]} for row in batch]
            vertex_collection.insert_many(documents, overwrite=True)
        for batch in _chunks(edges, batch_size):
            documents = [
                {"_from": f"{VERTEX_COLLECTION}/{row['src']}", "_to": f"{VERTEX_COLLECTION}/{row['dst']}"}
                for row in batch
            ]
            edge_collection.insert_many(documents, overwrite=True)
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

    def _bind_vars(self, params: dict[str, Any]) -> dict[str, Any]:
        """Reshapes logical params (e.g. {"start_id": "123"}) into AQL bind
        variables. Workload/runner code only ever knows the logical
        `start_id`/`src`/`dst`/`ml_target` names shared across every
        adapter; this is where ArangoDB's document-handle requirement
        (`developers/123`, not bare `123`) is satisfied without leaking
        into workloads/."""
        bind_vars: dict[str, Any] = {}
        if "start_id" in params:
            bind_vars["start_key"] = params["start_id"]
            bind_vars["start_id"] = f"{VERTEX_COLLECTION}/{params['start_id']}"
        if "ml_target" in params:
            bind_vars["ml_target"] = params["ml_target"]
        if "src" in params:
            bind_vars["src_id"] = f"{VERTEX_COLLECTION}/{params['src']}"
        if "dst" in params:
            bind_vars["dst_id"] = f"{VERTEX_COLLECTION}/{params['dst']}"
        return bind_vars

    def execute(self, query_name: str, params: dict[str, Any]) -> ExecuteResult:
        query = self.QUERIES[query_name]
        bind_vars = self._bind_vars(params)
        start_ns = time.perf_counter_ns()
        cursor = cast(Cursor, self._require_db.aql.execute(query, bind_vars=bind_vars))
        rows = list(cursor)
        end_ns = time.perf_counter_ns()
        normalized_rows = [row if isinstance(row, dict) else {"value": row} for row in rows]
        return ExecuteResult(rows=normalized_rows, latency_ms=(end_ns - start_ns) / 1e6)

    def footprint(self) -> FootprintResult:
        try:
            stats = self._require_db.collection(VERTEX_COLLECTION).statistics()
            figures = stats.get("figures", {}) if isinstance(stats, dict) else {}
            stored_bytes = figures.get("documentsSize")
            if stored_bytes is None:
                raise KeyError("documentsSize not present in collection statistics")
            return FootprintResult(observable=True, stored_bytes=int(stored_bytes))
        except Exception as exc:  # noqa: BLE001 - footprint is best-effort per platform
            return FootprintResult(observable=False, note=f"collection statistics not observable: {exc!r}")


def _chunks(rows: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [rows[i : i + size] for i in range(0, len(rows), size)]
