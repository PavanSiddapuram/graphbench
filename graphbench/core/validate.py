"""Cross-platform result-equality gate. Before any measurement is trusted,
every logical query is run against a fixed set of sample nodes on every
platform and the fingerprints are compared. A Cypher query returning
distinct nodes where an AQL query returns paths would make one database
look 30x faster for no real reason - this catches that before a single
latency number is published.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from graphbench.core.adapter import Adapter

WHOLE_GRAPH_SENTINEL = "<whole-graph>"


def canonical_fingerprint(rows: list[dict[str, Any]]) -> str:
    """sha256 over the canonicalised, sorted result set. Row order and
    dict-key order are normalized away here; adapters are responsible for
    returning comparable Python types (e.g. node ids as strings) so two
    platforms describing the same logical result produce the same
    fingerprint. `default=str` only fires for values json can't natively
    encode (e.g. a driver-specific temporal type), which is itself worth
    surfacing rather than crashing the gate.
    """
    row_strings = sorted(json.dumps(row, sort_keys=True, default=str) for row in rows)
    canonical = "\n".join(row_strings)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Mismatch:
    query_name: str
    node_id: str
    fingerprints: dict[str, str]  # platform -> fingerprint


@dataclass(frozen=True, slots=True)
class ValidationResult:
    ok: bool
    mismatches: list[Mismatch]


def run_equality_gate(
    adapters: dict[str, Adapter],
    node_parameterized_queries: dict[str, Callable[[str], dict[str, Any]]],
    whole_graph_queries: list[str],
    sample_node_ids: list[str],
) -> ValidationResult:
    """Runs every (query_name, node_id) pair against every adapter for the
    node-parameterized queries (hop_1/2/3, point_lookup, filtered_lookup -
    each keyed to its own param_builder, since filtered_lookup needs an
    extra ml_target bind value that hop_1 doesn't), plus every whole-graph
    query once (agg_by_label), and compares fingerprints across platforms.
    Adapters must already be connected and loaded with the identical
    dataset."""
    mismatches: list[Mismatch] = []

    for query_name, param_builder in node_parameterized_queries.items():
        for node_id in sample_node_ids:
            params = param_builder(node_id)
            fingerprints = {
                platform: canonical_fingerprint(adapter.execute(query_name, params).rows)
                for platform, adapter in adapters.items()
            }
            if len(set(fingerprints.values())) > 1:
                mismatches.append(Mismatch(query_name=query_name, node_id=node_id, fingerprints=fingerprints))

    for query_name in whole_graph_queries:
        fingerprints = {
            platform: canonical_fingerprint(adapter.execute(query_name, {}).rows)
            for platform, adapter in adapters.items()
        }
        if len(set(fingerprints.values())) > 1:
            mismatches.append(
                Mismatch(query_name=query_name, node_id=WHOLE_GRAPH_SENTINEL, fingerprints=fingerprints)
            )

    return ValidationResult(ok=not mismatches, mismatches=mismatches)


def format_diff(result: ValidationResult) -> str:
    """Human-readable diff for `make validate` - which platforms disagree,
    on which query/node, and what each one returned. A genuine semantic
    mismatch is a finding to report, not something to paper over by
    loosening the comparison."""
    if result.ok:
        return "equality gate passed: all platforms agree on every sampled query/node pair"

    lines = [f"equality gate FAILED: {len(result.mismatches)} mismatch(es)"]
    for mismatch in result.mismatches:
        lines.append(f"  query={mismatch.query_name} node={mismatch.node_id}")
        for platform, fingerprint in sorted(mismatch.fingerprints.items()):
            lines.append(f"    {platform}: {fingerprint}")
    return "\n".join(lines)
