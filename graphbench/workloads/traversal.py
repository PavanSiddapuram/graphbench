"""Logical traversal workloads: hop_1, hop_2, hop_3. This module only
knows the logical name and how to build params from a start node id -
never query text; every adapter's QUERIES dict defines these three names.
"""

from __future__ import annotations

from typing import Any

WORKLOAD_NAMES: list[str] = ["hop_1", "hop_2", "hop_3"]


def param_builder(node_id: str) -> dict[str, Any]:
    return {"start_id": node_id}
