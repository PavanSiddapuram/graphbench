"""Degree-stratified start-node selection with a fixed seed. Runs once;
the output (data/start_nodes.json) is committed and replayed identically
on every platform - see CLAUDE.md's "Degree stratification" rule. Uniform
random sampling would produce a bimodal distribution where p95 measures
how many hubs the sampler happened to pick, not database performance.
"""

from __future__ import annotations

import csv
import json
import random
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

WORKLOADS_CONFIG = Path("config/workloads.yaml")


@dataclass(frozen=True, slots=True)
class StartNodes:
    seed: int
    degree_bands: dict[str, list[float]]  # percentile ranges, e.g. {"low": [10, 30]}
    nodes_per_band: dict[str, list[str]]
    equality_gate_nodes: list[str]


def load_edges(edges_csv: Path) -> list[tuple[str, str]]:
    with edges_csv.open(newline="") as f:
        reader = csv.DictReader(f)
        return [(row["src"], row["dst"]) for row in reader]


def compute_degrees(edges: list[tuple[str, str]]) -> Counter[str]:
    degree: Counter[str] = Counter()
    for src, dst in edges:
        degree[src] += 1
        degree[dst] += 1
    return degree


def _band_candidates(sorted_nodes: list[str], lo_pct: float, hi_pct: float) -> list[str]:
    n = len(sorted_nodes)
    lo_idx = int(lo_pct / 100 * (n - 1))
    hi_idx = int(hi_pct / 100 * (n - 1))
    return sorted_nodes[lo_idx : hi_idx + 1]


def select_start_nodes(
    edges: list[tuple[str, str]],
    seed: int,
    degree_bands: dict[str, list[float]],
    nodes_per_band: int,
    equality_gate_size: int,
) -> StartNodes:
    degree = compute_degrees(edges)
    # sort ascending by (degree, node_id) so percentile indexing is
    # deterministic even when many nodes share the same degree
    sorted_nodes = sorted(degree, key=lambda node: (degree[node], node))

    rng = random.Random(seed)
    band_selection: dict[str, list[str]] = {}
    for band_name in sorted(degree_bands):  # deterministic iteration order
        lo_pct, hi_pct = degree_bands[band_name]
        candidates = _band_candidates(sorted_nodes, lo_pct, hi_pct)
        k = min(nodes_per_band, len(candidates))
        band_selection[band_name] = sorted(rng.sample(candidates, k))

    all_selected = sorted({node for nodes in band_selection.values() for node in nodes})
    gate_k = min(equality_gate_size, len(all_selected))
    equality_gate_nodes = sorted(rng.sample(all_selected, gate_k))

    return StartNodes(
        seed=seed,
        degree_bands=degree_bands,
        nodes_per_band=band_selection,
        equality_gate_nodes=equality_gate_nodes,
    )


def write_start_nodes(start_nodes: StartNodes, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(start_nodes), indent=2, sort_keys=True) + "\n")


def main() -> None:
    config = yaml.safe_load(WORKLOADS_CONFIG.read_text())
    sampling = config["sampling"]
    dataset = config["dataset"]

    edges = load_edges(Path(dataset["edges_csv"]))
    start_nodes = select_start_nodes(
        edges,
        seed=sampling["seed"],
        degree_bands=sampling["degree_bands"],
        nodes_per_band=sampling["start_nodes_per_band"],
        equality_gate_size=sampling["equality_gate_sample_size"],
    )
    write_start_nodes(start_nodes, Path(dataset["start_nodes"]))
    for band, nodes in start_nodes.nodes_per_band.items():
        print(f"{band}: {len(nodes)} start nodes")
    print(f"equality_gate: {len(start_nodes.equality_gate_nodes)} nodes")


if __name__ == "__main__":
    main()
