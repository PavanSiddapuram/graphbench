"""Writes data/nodes.csv, data/edges.csv and data/manifest.json. This is
the only place under dataset/ that writes to data/ - nothing downstream
regenerates these files.
"""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from graphbench.dataset.sample import SampleResult


@dataclass(frozen=True, slots=True)
class Manifest:
    source_url: str
    source_license_url: str
    retrieved_at_iso: str
    node_count: int
    relationship_count: int
    sample_seed: int | None
    sample_method: str
    nodes_csv_sha256: str
    edges_csv_sha256: str


def write_dataset(
    result: SampleResult,
    labels: dict[str, str],
    nodes_csv: Path,
    edges_csv: Path,
    manifest_path: Path,
    source_url: str,
    source_license_url: str,
) -> Manifest:
    nodes_csv.parent.mkdir(parents=True, exist_ok=True)

    with nodes_csv.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "label", "ml_target"])
        for node_id in result.node_ids:
            writer.writerow([node_id, "Developer", labels.get(node_id, "")])

    with edges_csv.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["src", "dst", "type"])
        for src, dst in result.edges:
            writer.writerow([src, dst, "FOLLOWS"])

    manifest = Manifest(
        source_url=source_url,
        source_license_url=source_license_url,
        retrieved_at_iso=datetime.now(UTC).isoformat(),
        node_count=len(result.node_ids),
        relationship_count=len(result.edges),
        sample_seed=result.seed,
        sample_method=result.method,
        nodes_csv_sha256=_sha256_file(nodes_csv),
        edges_csv_sha256=_sha256_file(edges_csv),
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(asdict(manifest), indent=2, sort_keys=True) + "\n")
    return manifest


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()
