from graphbench.core.record import Record
from graphbench.core.runner import queue_delay_trend_ms_per_min, run_read_workload
from tests.fakes import FakeAdapter


def _param_builder(node_id: str) -> dict[str, str]:
    return {"start_id": node_id}


def test_run_read_workload_produces_expected_phase_counts(tmp_path) -> None:
    nodes_csv = tmp_path / "nodes.csv"
    edges_csv = tmp_path / "edges.csv"
    nodes_csv.write_text("id,label,ml_target\n0,Developer,0\n1,Developer,1\n2,Developer,0\n")
    edges_csv.write_text("src,dst,type\n0,1,FOLLOWS\n1,2,FOLLOWS\n")

    adapter = FakeAdapter()
    adapter.connect()
    adapter.load(nodes_csv, edges_csv, batch_size=1000)

    records = run_read_workload(
        adapter,
        platform="fake",
        run_id="test-run",
        workload="hop_1",
        degree_band="mid",
        node_ids=["0", "1"],
        warmup_iterations=3,
        measured_iterations=5,
        param_builder=_param_builder,
    )

    assert len(records) == 8
    assert sum(1 for r in records if r.phase == "warmup") == 3
    assert sum(1 for r in records if r.phase == "measure") == 5
    assert all(r.ok for r in records)
    assert all(r.workload == "hop_1" for r in records)
    assert all(r.degree_band == "mid" for r in records)


def test_run_read_workload_records_failures_without_raising(tmp_path) -> None:
    nodes_csv = tmp_path / "nodes.csv"
    edges_csv = tmp_path / "edges.csv"
    nodes_csv.write_text("id,label,ml_target\n0,Developer,0\n")
    edges_csv.write_text("src,dst,type\n")

    adapter = FakeAdapter(fail_query_names=frozenset({"hop_1"}))
    adapter.connect()
    adapter.load(nodes_csv, edges_csv, batch_size=1000)

    records = run_read_workload(
        adapter,
        platform="fake",
        run_id="test-run",
        workload="hop_1",
        degree_band="low",
        node_ids=["0"],
        warmup_iterations=0,
        measured_iterations=2,
        param_builder=_param_builder,
    )

    assert len(records) == 2
    assert all(not r.ok for r in records)
    assert all(r.error is not None for r in records)


def _record_with_queue_delay(start_ns: int, queue_delay_ms: float) -> Record:
    return Record(
        run_id="r",
        platform="p",
        workload="mixed",
        phase="measure",
        ok=True,
        actual_start_ns=start_ns,
        end_ns=start_ns + 1_000_000,
        latency_ms=1.0,
        intended_start_ns=start_ns,
        queue_delay_ms=queue_delay_ms,
    )


def test_queue_delay_trend_is_zero_for_flat_delay() -> None:
    records = [_record_with_queue_delay(i * 1_000_000_000, 5.0) for i in range(10)]
    assert queue_delay_trend_ms_per_min(records) == 0.0


def test_queue_delay_trend_is_positive_when_falling_behind() -> None:
    # one second apart, queue delay growing linearly -> generator falling behind
    records = [_record_with_queue_delay(i * 1_000_000_000, float(i)) for i in range(60)]
    trend = queue_delay_trend_ms_per_min(records)
    assert trend > 0


def test_queue_delay_trend_needs_at_least_two_points() -> None:
    assert queue_delay_trend_ms_per_min([_record_with_queue_delay(0, 1.0)]) == 0.0
