"""Logical aggregation workload: agg_by_label. Whole-graph, no node
parameter - counts nodes grouped by the ml_target property. The dataset
has a single node label and a single relationship type (see the README's
dataset section), so this is the one property with real grouping value;
that is a documented workload-realism caveat, not a hidden one.
"""

from __future__ import annotations

WORKLOAD_NAMES: list[str] = ["agg_by_label"]
