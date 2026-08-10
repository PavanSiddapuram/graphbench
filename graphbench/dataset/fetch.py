"""Downloads the MUSAE GitHub developer-network dataset (Rozemberczki &
Sarkar, "Multi-scale Attributed Node Embedding", Journal of Complex
Networks 2021) from its public GitHub mirror:
https://github.com/benedekrozemberczki/MUSAE

37,700 developer nodes, 289,003 mutual-follower edges, one binary label
per node (ml_target: web vs. ml developer) - already inside the
assignment's required 100k-500k relationship range.

Only GitHub-hosted sources were reachable from the environment this file
was authored in (see CLAUDE.md's "Known environment constraint"); the
original SNAP-style dataset hosts this project would otherwise prefer were
not. Pinning to a branch (not a commit) is a known reproducibility gap -
see results/failures.md - mitigated by recording the downloaded content's
own SHA256 in data/manifest.json so any drift is detectable.
"""

from __future__ import annotations

import hashlib
import urllib.request
from dataclasses import dataclass
from pathlib import Path

_BASE_URL = "https://raw.githubusercontent.com/benedekrozemberczki/MUSAE/master"
EDGES_URL = f"{_BASE_URL}/input/edges/git_edges.csv"
TARGET_URL = f"{_BASE_URL}/input/target/git_target.csv"


@dataclass(frozen=True, slots=True)
class FetchedFile:
    url: str
    path: Path
    sha256: str
    byte_count: int


def _download(url: str, dest: Path, timeout_s: float = 60) -> FetchedFile:
    dest.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "graphbench-dataset-fetch"})
    with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310
        data = response.read()
    dest.write_bytes(data)
    return FetchedFile(url=url, path=dest, sha256=hashlib.sha256(data).hexdigest(), byte_count=len(data))


def fetch_raw(raw_dir: Path) -> tuple[FetchedFile, FetchedFile]:
    """Downloads the raw edge list and node-label file. Raises on any
    network failure rather than falling back to a cached or synthetic copy -
    per the prime directive, a failed fetch is a failure to report, not a
    reason to invent data."""
    edges = _download(EDGES_URL, raw_dir / "git_edges.csv")
    target = _download(TARGET_URL, raw_dir / "git_target.csv")
    return edges, target


if __name__ == "__main__":
    for fetched in fetch_raw(Path("data/raw")):
        print(f"{fetched.path}: {fetched.byte_count} bytes sha256={fetched.sha256}")
