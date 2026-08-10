"""Adapter contract: everything a benchmark adapter must implement for one
graph database. Adapters know their database; they never know what a
workload is - QUERIES is the only place query-language differences live.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class LoadResult:
    """Outcome of one load() call, timed end-to-end by the adapter itself
    so network/driver overhead specific to that platform is included."""

    node_count: int
    relationship_count: int
    wall_clock_ms: float
    nodes_per_sec: float
    relationships_per_sec: float


@dataclass(frozen=True, slots=True)
class ExecuteResult:
    """Outcome of one execute() call.

    `rows` feeds the cross-platform fingerprint gate in core/validate.py, so
    adapters must return the query's actual result rows (as plain dicts of
    JSON-serialisable values) rather than driver-specific record objects.
    Do not sort `rows` here unless the query itself has an ORDER BY -
    canonicalisation for comparison happens centrally in validate.py, and
    silently sorting here would hide a real ordering difference between
    platforms.
    """

    rows: list[dict[str, Any]]
    latency_ms: float


@dataclass(frozen=True, slots=True)
class FootprintResult:
    """Resource usage the platform actually exposes.

    Set `observable=False` with a `note` explaining why rather than
    guessing a number - section 5.2 of the assignment explicitly allows
    "not observable" as an answer.
    """

    observable: bool
    stored_bytes: int | None = None
    memory_bytes: int | None = None
    note: str | None = None


@runtime_checkable
class Adapter(Protocol):
    """One implementation per graph database (or per wire protocol, when
    several platforms share one - e.g. Bolt+Cypher covers CognoDB, Neo4j
    AuraDB and Memgraph Cloud through a single adapters/bolt.py).
    """

    QUERIES: ClassVar[dict[str, str]]

    def connect(self) -> None:
        """Open the connection. Must not silently retry; a connection
        failure is a Record with ok=False, not a retry loop."""
        ...

    def close(self) -> None: ...

    def rtt_probe_ms(self, samples: int = 100) -> list[float]:
        """Round-trip time for a trivial query (e.g. `RETURN 1`), timed
        with time.perf_counter_ns(). Used to separate network latency from
        database latency in the reported percentiles."""
        ...

    def create_indexes(self) -> list[str]:
        """Create whatever indexes this platform needs for the lookup
        workloads and return a human-readable description of each index
        created, so the README can state which properties are indexed."""
        ...

    def load(self, nodes_path: Path, edges_path: Path, batch_size: int) -> LoadResult: ...

    def execute(self, query_name: str, params: dict[str, Any]) -> ExecuteResult:
        """Run self.QUERIES[query_name] with params bound and return the
        result rows plus latency. query_name is a logical workload name
        (e.g. "hop_2"), never raw query text."""
        ...

    def footprint(self) -> FootprintResult: ...
