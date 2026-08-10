"""Orchestrates fetch -> sample -> write for `make dataset`.

Run as `python -m graphbench.dataset.build`.
"""

from __future__ import annotations

import csv
from pathlib import Path

import yaml

from graphbench.dataset.fetch import EDGES_URL, fetch_raw
from graphbench.dataset.manifest import write_dataset
from graphbench.dataset.sample import load_edge_list, sample_to_range

LICENSE_URL = "https://github.com/benedekrozemberczki/MUSAE/blob/master/LICENSE"
WORKLOADS_CONFIG = Path("config/workloads.yaml")


def _load_seed() -> int:
    config = yaml.safe_load(WORKLOADS_CONFIG.read_text())
    seed: int = config["sampling"]["seed"]
    return seed


def _load_labels(target_csv: Path) -> dict[str, str]:
    with target_csv.open(newline="") as f:
        reader = csv.DictReader(f)
        return {row["id"]: row["ml_target"] for row in reader}


def main() -> None:
    seed = _load_seed()
    raw_dir = Path("data/raw")
    edges_file, target_file = fetch_raw(raw_dir)

    edges = load_edge_list(edges_file.path)
    labels = _load_labels(target_file.path)
    result = sample_to_range(edges, seed=seed)

    manifest = write_dataset(
        result,
        labels,
        nodes_csv=Path("data/nodes.csv"),
        edges_csv=Path("data/edges.csv"),
        manifest_path=Path("data/manifest.json"),
        source_url=EDGES_URL,
        source_license_url=LICENSE_URL,
    )
    print(f"nodes={manifest.node_count} relationships={manifest.relationship_count}")
    print(f"sample_method={manifest.sample_method} seed={manifest.sample_seed}")
    print(f"nodes.csv sha256={manifest.nodes_csv_sha256}")
    print(f"edges.csv sha256={manifest.edges_csv_sha256}")


if __name__ == "__main__":
    main()
