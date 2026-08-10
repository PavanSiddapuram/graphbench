"""CDF and knee-curve chart generation from raw Records. No chart is ever
generated from invented data - every function takes real Record objects
loaded from results/raw/*.jsonl and raises if there is nothing to plot,
rather than silently rendering an empty or placeholder figure.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from graphbench.core.record import Record
from graphbench.core.stats import group_by


def plot_latency_cdf(records: list[Record], workload: str, out_path: Path) -> None:
    """One CDF line per platform for `workload`'s measured, successful
    latencies. Bar charts of mean latency are an anti-pattern per
    CLAUDE.md; this is the replacement."""
    scoped = [r for r in records if r.workload == workload and r.phase == "measure" and r.ok]
    if not scoped:
        raise ValueError(f"no measured records for workload={workload!r}; nothing to plot")

    fig, ax = plt.subplots()
    for platform_key, group in sorted(group_by(scoped, "platform").items()):
        latencies = sorted(r.latency_ms for r in group)
        n = len(latencies)
        ax.plot(latencies, [(i + 1) / n for i in range(n)], label=platform_key[0])
    ax.set_xlabel("latency (ms)")
    ax.set_ylabel("CDF")
    ax.set_title(f"{workload} latency CDF")
    ax.legend()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)


def plot_throughput_vs_concurrency(records: list[Record], duration_seconds: float, out_path: Path) -> None:
    """Sustained QPS at each concurrency level - the throughput knee
    curve, from the mixed workload sweep."""
    scoped = [r for r in records if r.concurrency is not None and r.ok]
    if not scoped:
        raise ValueError("no mixed-workload records with concurrency set; nothing to plot")

    fig, ax = plt.subplots()
    for platform_key, group in sorted(group_by(scoped, "platform").items()):
        by_concurrency = group_by(group, "concurrency")
        concurrencies = sorted(int(key[0]) for key in by_concurrency)
        qps = [len(by_concurrency[(str(c),)]) / duration_seconds for c in concurrencies]
        ax.plot(concurrencies, qps, marker="o", label=platform_key[0])
    ax.set_xlabel("concurrent clients")
    ax.set_ylabel("sustained QPS")
    ax.set_title("throughput vs. concurrency")
    ax.legend()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)


def plot_burst_credit_timeseries(records: list[Record], platform: str, out_path: Path) -> None:
    """Latency over wall-clock time for one platform's mixed-workload run,
    to reveal a CPU-credit exhaustion cliff if the run is long enough
    (CLAUDE.md requires >=20 minutes at the top concurrency for exactly
    this reason)."""
    scoped = sorted(
        (r for r in records if r.platform == platform and r.concurrency is not None and r.ok),
        key=lambda r: r.actual_start_ns,
    )
    if not scoped:
        raise ValueError(f"no mixed-workload records for platform={platform!r}; nothing to plot")

    t0 = scoped[0].actual_start_ns
    xs = [(r.actual_start_ns - t0) / 1e9 / 60 for r in scoped]
    ys = [r.latency_ms for r in scoped]

    fig, ax = plt.subplots()
    ax.plot(xs, ys, linewidth=0.5)
    ax.set_xlabel("minutes since run start")
    ax.set_ylabel("latency (ms)")
    ax.set_title(f"{platform}: mixed workload latency over time")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)
