"""Seeded, deterministic sampling that preserves connectivity, so hop_2 and
hop_3 traversal workloads still have real multi-hop structure to walk.

If the source graph already fits the assignment's 100k-500k relationship
range, sampling is the identity transform - no edges are discarded for no
reason. Only a source exceeding the range triggers the seeded BFS/snowball
sampler below.
"""

from __future__ import annotations

import csv
import random
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

MIN_RELATIONSHIPS = 100_000
MAX_RELATIONSHIPS = 500_000


@dataclass(frozen=True, slots=True)
class SampleResult:
    node_ids: list[str]
    edges: list[tuple[str, str]]
    method: str
    seed: int | None


def load_edge_list(edges_csv: Path, src_col: str = "id_1", dst_col: str = "id_2") -> list[tuple[str, str]]:
    with edges_csv.open(newline="") as f:
        reader = csv.DictReader(f)
        return [(row[src_col], row[dst_col]) for row in reader]


def snowball_sample(edges: list[tuple[str, str]], target_max: int, seed: int) -> SampleResult:
    """Seeded BFS from one seeded-random start node; neighbor visit order
    within each frontier step is shuffled by the same seeded RNG, so the
    result is deterministic for a given (edges, seed) pair but not merely
    "first N nodes by id". Stops once the induced edge count reaches
    target_max.
    """
    rng = random.Random(seed)
    adjacency: dict[str, list[str]] = defaultdict(list)
    for a, b in edges:
        adjacency[a].append(b)
        adjacency[b].append(a)

    start = rng.choice(sorted(adjacency))
    visited: set[str] = {start}
    queue: deque[str] = deque([start])
    induced_edge_count = 0

    while queue:
        node = queue.popleft()
        neighbors = sorted(adjacency[node])
        rng.shuffle(neighbors)
        for neighbor in neighbors:
            if neighbor in visited:
                continue
            visited.add(neighbor)
            induced_edge_count += sum(1 for nb in adjacency[neighbor] if nb in visited)
            queue.append(neighbor)
            if induced_edge_count >= target_max:
                queue.clear()
                break

    sampled_edges = [(a, b) for a, b in edges if a in visited and b in visited]
    return SampleResult(node_ids=sorted(visited), edges=sampled_edges, method="seeded-bfs-snowball", seed=seed)


def sample_to_range(
    edges: list[tuple[str, str]],
    seed: int,
    min_rel: int = MIN_RELATIONSHIPS,
    max_rel: int = MAX_RELATIONSHIPS,
) -> SampleResult:
    if len(edges) > max_rel:
        return snowball_sample(edges, target_max=max_rel, seed=seed)

    if len(edges) < min_rel:
        raise ValueError(
            f"source graph has only {len(edges)} relationships, below the "
            f"required minimum of {min_rel}; this dataset cannot satisfy the "
            "assignment's 100k-500k range without a different source"
        )

    nodes = sorted({n for pair in edges for n in pair})
    return SampleResult(node_ids=nodes, edges=edges, method="identity-already-in-range", seed=None)
