from graphbench.core.validate import canonical_fingerprint, run_equality_gate
from tests.fakes import FakeAdapter


def test_fingerprint_ignores_row_order() -> None:
    a = canonical_fingerprint([{"id": "1"}, {"id": "2"}])
    b = canonical_fingerprint([{"id": "2"}, {"id": "1"}])
    assert a == b


def test_fingerprint_ignores_dict_key_order() -> None:
    a = canonical_fingerprint([{"id": "1", "ml_target": "0"}])
    b = canonical_fingerprint([{"ml_target": "0", "id": "1"}])
    assert a == b


def test_fingerprint_differs_for_different_content() -> None:
    a = canonical_fingerprint([{"id": "1"}])
    b = canonical_fingerprint([{"id": "2"}])
    assert a != b


def _seeded_adapter(nodes_csv, edges_csv) -> FakeAdapter:
    adapter = FakeAdapter()
    adapter.connect()
    adapter.load(nodes_csv, edges_csv, batch_size=1000)
    return adapter


def test_equality_gate_passes_for_identical_adapters(tmp_path) -> None:
    nodes_csv = tmp_path / "nodes.csv"
    edges_csv = tmp_path / "edges.csv"
    nodes_csv.write_text("id,label,ml_target\n0,Developer,0\n1,Developer,1\n2,Developer,0\n")
    edges_csv.write_text("src,dst,type\n0,1,FOLLOWS\n1,2,FOLLOWS\n")

    adapters = {"platform_a": _seeded_adapter(nodes_csv, edges_csv), "platform_b": _seeded_adapter(nodes_csv, edges_csv)}

    result = run_equality_gate(
        adapters,
        node_parameterized_queries={"hop_1": lambda node_id: {"start_id": node_id}},
        whole_graph_queries=["agg_by_label"],
        sample_node_ids=["0", "1"],
    )

    assert result.ok
    assert result.mismatches == []


def test_equality_gate_catches_a_real_mismatch(tmp_path) -> None:
    nodes_csv = tmp_path / "nodes.csv"
    edges_csv_a = tmp_path / "edges_a.csv"
    edges_csv_b = tmp_path / "edges_b.csv"
    nodes_csv.write_text("id,label,ml_target\n0,Developer,0\n1,Developer,1\n2,Developer,0\n")
    # platform_b's data disagrees with platform_a's: an extra edge
    edges_csv_a.write_text("src,dst,type\n0,1,FOLLOWS\n")
    edges_csv_b.write_text("src,dst,type\n0,1,FOLLOWS\n0,2,FOLLOWS\n")

    adapters = {
        "platform_a": _seeded_adapter(nodes_csv, edges_csv_a),
        "platform_b": _seeded_adapter(nodes_csv, edges_csv_b),
    }

    result = run_equality_gate(
        adapters,
        node_parameterized_queries={"hop_1": lambda node_id: {"start_id": node_id}},
        whole_graph_queries=[],
        sample_node_ids=["0"],
    )

    assert not result.ok
    assert len(result.mismatches) == 1
    assert result.mismatches[0].query_name == "hop_1"
    assert result.mismatches[0].node_id == "0"
