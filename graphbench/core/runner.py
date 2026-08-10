"""Warmup + measurement loop for read workloads, and the open-loop load
generator used by the mixed workload. Timing is always
time.perf_counter_ns() - never time.time(). Every call becomes exactly one
Record, success or failure; there is no retry-on-error inside these loops.
"""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from graphbench.core.adapter import Adapter
from graphbench.core.record import DegreeBand, Record


def run_read_workload(
    adapter: Adapter,
    platform: str,
    run_id: str,
    workload: str,
    degree_band: DegreeBand,
    node_ids: list[str],
    warmup_iterations: int,
    measured_iterations: int,
    param_builder: Callable[[str], dict[str, Any]],
) -> list[Record]:
    """Runs `workload` against `node_ids` (cycled), warmup_iterations
    (phase="warmup") then measured_iterations (phase="measure")."""
    records: list[Record] = []
    total = warmup_iterations + measured_iterations

    for i in range(total):
        node_id = node_ids[i % len(node_ids)]
        phase = "warmup" if i < warmup_iterations else "measure"
        params = param_builder(node_id)

        start_ns = time.perf_counter_ns()
        try:
            result = adapter.execute(workload, params)
            end_ns = time.perf_counter_ns()
            records.append(
                Record(
                    run_id=run_id,
                    platform=platform,
                    workload=workload,
                    phase=phase,
                    ok=True,
                    actual_start_ns=start_ns,
                    end_ns=end_ns,
                    latency_ms=(end_ns - start_ns) / 1e6,
                    degree_band=degree_band,
                    start_node_id=node_id,
                    rows_returned=len(result.rows),
                )
            )
        except Exception as exc:  # noqa: BLE001 - failure becomes a Record, never a retry
            end_ns = time.perf_counter_ns()
            records.append(
                Record(
                    run_id=run_id,
                    platform=platform,
                    workload=workload,
                    phase=phase,
                    ok=False,
                    actual_start_ns=start_ns,
                    end_ns=end_ns,
                    latency_ms=(end_ns - start_ns) / 1e6,
                    degree_band=degree_band,
                    start_node_id=node_id,
                    error=repr(exc),
                )
            )
    return records


def _issue_one(
    adapter: Adapter,
    platform: str,
    run_id: str,
    workload: str,
    intended_start_ns: int,
    params: dict[str, Any],
    concurrency: int,
    out: queue.Queue[Record],
) -> None:
    actual_start_ns = time.perf_counter_ns()
    try:
        result = adapter.execute(workload, params)
        end_ns = time.perf_counter_ns()
        out.put(
            Record(
                run_id=run_id,
                platform=platform,
                workload=workload,
                phase="measure",
                ok=True,
                actual_start_ns=actual_start_ns,
                end_ns=end_ns,
                latency_ms=(end_ns - actual_start_ns) / 1e6,
                intended_start_ns=intended_start_ns,
                queue_delay_ms=(actual_start_ns - intended_start_ns) / 1e6,
                concurrency=concurrency,
                rows_returned=len(result.rows),
            )
        )
    except Exception as exc:  # noqa: BLE001 - failure becomes a Record, never a retry
        end_ns = time.perf_counter_ns()
        out.put(
            Record(
                run_id=run_id,
                platform=platform,
                workload=workload,
                phase="measure",
                ok=False,
                actual_start_ns=actual_start_ns,
                end_ns=end_ns,
                latency_ms=(end_ns - actual_start_ns) / 1e6,
                intended_start_ns=intended_start_ns,
                queue_delay_ms=(actual_start_ns - intended_start_ns) / 1e6,
                concurrency=concurrency,
                error=repr(exc),
            )
        )


def _client_loop(
    adapter: Adapter,
    platform: str,
    run_id: str,
    workload_picker: Callable[[], tuple[str, dict[str, Any]]],
    intended_starts_ns: list[int],
    concurrency: int,
    out: queue.Queue[Record],
) -> None:
    for intended_start_ns in intended_starts_ns:
        now_ns = time.perf_counter_ns()
        if intended_start_ns > now_ns:
            time.sleep((intended_start_ns - now_ns) / 1e9)
        workload, params = workload_picker()
        _issue_one(adapter, platform, run_id, workload, intended_start_ns, params, concurrency, out)


@dataclass(frozen=True, slots=True)
class OpenLoopResult:
    records: list[Record]
    queue_delay_trend_ms_per_min: float


def queue_delay_trend_ms_per_min(records: list[Record]) -> float:
    """Least-squares slope of queue_delay_ms over wall-clock time (minutes
    since the first request), in ms/minute. A positive slope means the
    generator is falling behind its intended schedule - see
    core.validate.check_queue_delay_trend, which turns this into a hard
    fail rather than a number quietly published in the README."""
    timed = [(r.actual_start_ns, r.queue_delay_ms) for r in records if r.queue_delay_ms is not None]
    if len(timed) < 2:
        return 0.0

    t0 = timed[0][0]
    xs = [(t - t0) / 1e9 / 60 for t, _ in timed]
    ys = [d for _, d in timed if d is not None]

    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    denominator = sum((x - mean_x) ** 2 for x in xs)
    if denominator == 0:
        return 0.0
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    return numerator / denominator


def run_open_loop(
    adapter_factory: Callable[[], Adapter],
    platform: str,
    run_id: str,
    workload_picker: Callable[[], tuple[str, dict[str, Any]]],
    concurrency: int,
    duration_seconds: float,
    intended_qps_per_client: float,
) -> OpenLoopResult:
    """Precomputes intended start times at intended_qps_per_client *
    concurrency total rate, split round-robin across `concurrency`
    persistent connections. Each connection runs its own schedule in a
    dedicated thread and blocks (never busy-waits) until its next intended
    tick; if a call runs long, the next one on that connection starts late
    and queue_delay_ms records exactly how late. This is deliberately not
    closed-loop (send -> wait -> send), which would hide tail latency by
    construction - see CLAUDE.md's "Open loop" rule.
    """
    total_rate = intended_qps_per_client * concurrency
    interval_ns = int(1e9 / total_rate)
    tick_count = int(duration_seconds * total_rate)

    out: queue.Queue[Record] = queue.Queue()
    adapters = [adapter_factory() for _ in range(concurrency)]
    for a in adapters:
        a.connect()

    base_ns = time.perf_counter_ns()
    per_client_starts: list[list[int]] = [[] for _ in range(concurrency)]
    for i in range(tick_count):
        per_client_starts[i % concurrency].append(base_ns + i * interval_ns)

    threads = [
        threading.Thread(
            target=_client_loop,
            args=(adapters[c], platform, run_id, workload_picker, per_client_starts[c], concurrency, out),
            daemon=True,
        )
        for c in range(concurrency)
    ]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        for a in adapters:
            a.close()

    records: list[Record] = []
    while not out.empty():
        records.append(out.get_nowait())

    return OpenLoopResult(records=records, queue_delay_trend_ms_per_min=queue_delay_trend_ms_per_min(records))
