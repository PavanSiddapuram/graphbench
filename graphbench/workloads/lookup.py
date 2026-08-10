"""Logical lookup workloads: point_lookup (by id - the primary/unique key
on every platform, see each adapter's create_indexes()) and filtered_lookup
(neighbors filtered by the ml_target property). The filter value is a
single fixed constant from config/workloads.yaml so every platform is
asked the identical question.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

WORKLOAD_NAMES: list[str] = ["point_lookup", "filtered_lookup"]

WORKLOADS_CONFIG = Path("config/workloads.yaml")
_ml_target_cache: str | None = None


def _filtered_lookup_ml_target() -> str:
    global _ml_target_cache
    if _ml_target_cache is None:
        config = yaml.safe_load(WORKLOADS_CONFIG.read_text())
        _ml_target_cache = config["lookup"]["filtered_lookup_ml_target"]
    return _ml_target_cache


def point_lookup_params(node_id: str) -> dict[str, Any]:
    return {"start_id": node_id}


def filtered_lookup_params(node_id: str) -> dict[str, Any]:
    return {"start_id": node_id, "ml_target": _filtered_lookup_ml_target()}


PARAM_BUILDERS = {
    "point_lookup": point_lookup_params,
    "filtered_lookup": filtered_lookup_params,
}
