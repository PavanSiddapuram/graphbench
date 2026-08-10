import pytest

from graphbench.dataset.sample import sample_to_range, snowball_sample


def _chain_graph(n: int) -> list[tuple[str, str]]:
    """A single connected path 0-1-2-...-n, so induced-edge-count math is
    easy to reason about by hand."""
    return [(str(i), str(i + 1)) for i in range(n)]


def test_sample_to_range_is_identity_when_already_in_range() -> None:
    edges = _chain_graph(150_000)  # 150,000 edges: inside [100k, 500k]
    result = sample_to_range(edges, seed=1, min_rel=100_000, max_rel=500_000)
    assert result.method == "identity-already-in-range"
    assert result.seed is None
    assert len(result.edges) == len(edges)


def test_sample_to_range_raises_below_minimum() -> None:
    edges = _chain_graph(10)
    with pytest.raises(ValueError):
        sample_to_range(edges, seed=1, min_rel=100_000, max_rel=500_000)


def test_snowball_sample_stays_connected_to_start() -> None:
    edges = _chain_graph(2_000)
    result = snowball_sample(edges, target_max=100, seed=3)
    nodes = set(result.node_ids)
    # every sampled edge's endpoints must be in the sampled node set
    for a, b in result.edges:
        assert a in nodes
        assert b in nodes
    assert len(result.edges) >= 100  # stopping condition is >=, not exact


def test_snowball_sample_is_deterministic_for_same_seed() -> None:
    edges = _chain_graph(2_000)
    result_a = snowball_sample(edges, target_max=200, seed=5)
    result_b = snowball_sample(edges, target_max=200, seed=5)
    assert result_a == result_b


def test_snowball_sample_can_differ_for_different_seed() -> None:
    # a graph with branching so different seeds can plausibly start
    # from different hubs and diverge
    edges = _chain_graph(50) + [("0", str(i)) for i in range(50, 500)]
    result_a = snowball_sample(edges, target_max=100, seed=1)
    result_b = snowball_sample(edges, target_max=100, seed=99)
    assert result_a.node_ids != result_b.node_ids or result_a.edges != result_b.edges


def test_sample_to_range_triggers_snowball_above_max() -> None:
    edges = _chain_graph(600_000)
    result = sample_to_range(edges, seed=1, min_rel=100_000, max_rel=500_000)
    assert result.method == "seeded-bfs-snowball"
    assert len(result.edges) <= 600_000
