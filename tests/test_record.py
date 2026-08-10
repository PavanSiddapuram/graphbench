from graphbench.core.record import Record


def test_jsonl_round_trip() -> None:
    record = Record(
        run_id="20260810T000000Z-abc1234",
        platform="cognodb",
        workload="hop_1",
        phase="measure",
        ok=True,
        actual_start_ns=1_000,
        end_ns=2_500_000,
        latency_ms=2.4,
        degree_band="mid",
        start_node_id="42",
        rows_returned=3,
        fingerprint="deadbeef",
    )

    line = record.to_jsonl()
    restored = Record.from_jsonl(line)

    assert restored == record


def test_jsonl_is_one_line() -> None:
    record = Record(
        run_id="r",
        platform="p",
        workload="w",
        phase="warmup",
        ok=False,
        actual_start_ns=0,
        end_ns=0,
        latency_ms=0.0,
        error="boom",
    )
    assert "\n" not in record.to_jsonl()


def test_optional_fields_default_none() -> None:
    record = Record(
        run_id="r",
        platform="p",
        workload="w",
        phase="measure",
        ok=True,
        actual_start_ns=0,
        end_ns=1,
        latency_ms=0.001,
    )
    assert record.intended_start_ns is None
    assert record.queue_delay_ms is None
    assert record.degree_band is None
    assert record.fingerprint is None
    assert record.node_count is None
