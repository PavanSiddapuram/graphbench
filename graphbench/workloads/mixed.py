"""Mixed read/write workload picker for the open-loop generator
(core/runner.run_open_loop). Reads are drawn evenly from hop_1 and
point_lookup; writes insert a new FOLLOWS edge between two existing nodes.
config/workloads.yaml's mixed_workload.read_write_ratio sets the split.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from typing import Any

READ_WORKLOADS: list[str] = ["hop_1", "point_lookup"]
WRITE_WORKLOAD = "insert_edge"


def parse_ratio(ratio: str) -> tuple[int, int]:
    read_str, write_str = ratio.split(":")
    return int(read_str), int(write_str)


def make_picker(
    node_ids: list[str],
    read_write_ratio: str,
    seed: int,
) -> Callable[[], tuple[str, dict[str, Any]]]:
    """Returns a workload_picker() closure for run_open_loop: each call
    returns (logical_workload_name, params), weighted by read_write_ratio.
    Seeded for a reproducible *schedule of what gets asked*; the Records
    the runner appends remain the source of truth, not this generator's
    internal state.
    """
    read_weight, write_weight = parse_ratio(read_write_ratio)
    rng = random.Random(seed)

    def picker() -> tuple[str, dict[str, Any]]:
        if rng.randint(1, read_weight + write_weight) <= read_weight:
            workload = rng.choice(READ_WORKLOADS)
            node_id = rng.choice(node_ids)
            return workload, {"start_id": node_id}
        src, dst = rng.sample(node_ids, 2)
        return WRITE_WORKLOAD, {"src": src, "dst": dst}

    return picker
