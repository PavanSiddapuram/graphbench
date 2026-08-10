from graphbench.core.sampler import compute_degrees, select_start_nodes

# a small deterministic graph: node "9" is a hub (degree 5), most others are
# degree 1-2, so percentile bands are unambiguous even at this size
EDGES = [
    ("9", "0"), ("9", "1"), ("9", "2"), ("9", "3"), ("9", "4"),
    ("0", "1"), ("2", "3"), ("5", "6"), ("7", "8"),
]

DEGREE_BANDS = {"low": [0, 30], "mid": [40, 60], "high": [90, 100]}


def test_compute_degrees_counts_both_endpoints() -> None:
    degree = compute_degrees(EDGES)
    assert degree["9"] == 5
    assert degree["0"] == 2  # appears in ("9","0") and ("0","1")
    assert degree["5"] == 1


def test_select_start_nodes_is_deterministic_for_same_seed() -> None:
    result_a = select_start_nodes(EDGES, seed=42, degree_bands=DEGREE_BANDS, nodes_per_band=2, equality_gate_size=2)
    result_b = select_start_nodes(EDGES, seed=42, degree_bands=DEGREE_BANDS, nodes_per_band=2, equality_gate_size=2)
    assert result_a == result_b


def test_select_start_nodes_differs_for_different_seed() -> None:
    result_a = select_start_nodes(EDGES, seed=1, degree_bands=DEGREE_BANDS, nodes_per_band=2, equality_gate_size=2)
    result_b = select_start_nodes(EDGES, seed=2, degree_bands=DEGREE_BANDS, nodes_per_band=2, equality_gate_size=2)
    assert result_a.nodes_per_band != result_b.nodes_per_band or result_a.equality_gate_nodes != result_b.equality_gate_nodes


def test_high_band_picks_the_hub() -> None:
    result = select_start_nodes(EDGES, seed=7, degree_bands=DEGREE_BANDS, nodes_per_band=2, equality_gate_size=2)
    assert "9" in result.nodes_per_band["high"]


def test_equality_gate_nodes_are_subset_of_selected_nodes() -> None:
    result = select_start_nodes(EDGES, seed=7, degree_bands=DEGREE_BANDS, nodes_per_band=2, equality_gate_size=3)
    all_selected = {n for nodes in result.nodes_per_band.values() for n in nodes}
    assert set(result.equality_gate_nodes) <= all_selected


def test_nodes_per_band_never_exceeds_requested_count() -> None:
    result = select_start_nodes(EDGES, seed=7, degree_bands=DEGREE_BANDS, nodes_per_band=100, equality_gate_size=2)
    for nodes in result.nodes_per_band.values():
        assert len(nodes) <= len({n for pair in EDGES for n in pair})
