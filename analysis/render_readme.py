"""Reads results/raw/*.jsonl and writes the results section between
<!-- BEGIN RESULTS --> / <!-- END RESULTS --> in README.md. This is the
only place README result tables are written - see CLAUDE.md's "README
tables are generated, not typed" rule. An empty results/raw/ produces an
honest "no runs recorded yet" table, never a fabricated one.
"""

from __future__ import annotations

import glob
from pathlib import Path

from graphbench.core.record import Record
from graphbench.core.stats import group_by, summarize_records

README_PATH = Path("README.md")
BEGIN_MARKER = "<!-- BEGIN RESULTS -->"
END_MARKER = "<!-- END RESULTS -->"
RAW_GLOB = "results/raw/*.jsonl"

READ_WORKLOADS = ["hop_1", "hop_2", "hop_3", "point_lookup", "filtered_lookup", "agg_by_label"]


def load_all_records() -> list[Record]:
    records: list[Record] = []
    for path in sorted(glob.glob(RAW_GLOB)):
        with open(path) as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    records.append(Record.from_jsonl(stripped))
    return records


def render_rtt_table(records: list[Record]) -> str:
    scoped = [r for r in records if r.workload == "rtt_probe" and r.ok]
    if not scoped:
        return "_No RTT probes recorded yet - run `make bench PLATFORM=<name>` for each platform._"
    lines = ["| Platform | n | p50 (ms) | p95 (ms) |", "|---|---|---|---|"]
    for platform_key, group in sorted(group_by(scoped, "platform").items()):
        summary = summarize_records(group)
        lines.append(f"| {platform_key[0]} | {summary.count} | {summary.p50_ms:.2f} | {summary.p95_ms:.2f} |")
    return "\n".join(lines)


def render_ingest_table(records: list[Record]) -> str:
    rows = [r for r in records if r.workload == "ingest" and r.ok]
    if not rows:
        return "_No ingest runs recorded yet - run `make load PLATFORM=<name>` for each platform._"
    lines = ["| Platform | Nodes/sec | Relationships/sec | Wall-clock (s) |", "|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: r.platform):
        seconds = r.latency_ms / 1000
        nodes_per_sec = (r.node_count / seconds) if r.node_count and seconds > 0 else 0.0
        rels_per_sec = (r.relationship_count / seconds) if r.relationship_count and seconds > 0 else 0.0
        lines.append(f"| {r.platform} | {nodes_per_sec:,.0f} | {rels_per_sec:,.0f} | {seconds:,.1f} |")
    return "\n".join(lines)


def render_read_workload_table(records: list[Record], workload: str) -> str:
    scoped = [r for r in records if r.workload == workload]
    if not scoped:
        return f"_No `{workload}` runs recorded yet._"

    lines = ["| Platform | Degree band | n | p50 (ms) | p95 (ms) |", "|---|---|---|---|---|"]
    for (platform, band), group in sorted(group_by(scoped, "platform", "degree_band").items()):
        measured = [r for r in group if r.phase == "measure" and r.ok]
        if not measured:
            continue
        summary = summarize_records(group)
        lines.append(f"| {platform} | {band} | {summary.count} | {summary.p50_ms:.2f} | {summary.p95_ms:.2f} |")

    if len(lines) == 2:
        return f"_No completed `{workload}` measurements recorded yet._"
    return "\n".join(lines)


def render_footprint_table(records: list[Record]) -> str:
    # footprint() is called out-of-band from the FootprintResult dataclass,
    # not through Record/JSONL (it is a point-in-time platform property,
    # not a per-request measurement) - see core/adapter.py's docstring.
    return (
        "_Footprint (stored data size / memory) is captured via each adapter's `footprint()` "
        "call, not through results/raw/*.jsonl - it has not been run yet against any platform. "
        "See `graphbench.core.adapter.FootprintResult`._"
    )


def render_mixed_workload_table(records: list[Record]) -> str:
    scoped = [r for r in records if r.concurrency is not None]
    if not scoped:
        return "_No mixed-workload sweep recorded yet - run `make sweep PLATFORM=<name>`._"

    lines = ["| Platform | Concurrency | Sustained QPS | Queue delay trend |", "|---|---|---|---|"]
    for (platform, concurrency), group in sorted(
        group_by(scoped, "platform", "concurrency").items(), key=lambda kv: (kv[0][0], int(kv[0][1]))
    ):
        ok_count = sum(1 for r in group if r.ok)
        lines.append(f"| {platform} | {concurrency} | n={ok_count} | see results/raw for queue_delay_ms |")
    return "\n".join(lines)


def render_results_section(records: list[Record]) -> str:
    parts = [
        "### RTT floor",
        "",
        render_rtt_table(records),
        "",
        "### Ingest throughput",
        "",
        render_ingest_table(records),
        "",
        "### Footprint",
        "",
        render_footprint_table(records),
        "",
        "### Mixed workload (concurrency sweep)",
        "",
        render_mixed_workload_table(records),
        "",
        "### Read workload latency (p50 / p95 by degree band)",
        "",
    ]
    for workload in READ_WORKLOADS:
        parts.append(f"**{workload}**")
        parts.append("")
        parts.append(render_read_workload_table(records, workload))
        parts.append("")
    return "\n".join(parts)


def update_readme(section: str) -> None:
    text = README_PATH.read_text()
    if BEGIN_MARKER not in text or END_MARKER not in text:
        raise ValueError(f"README.md is missing {BEGIN_MARKER} / {END_MARKER} markers")
    before, rest = text.split(BEGIN_MARKER, 1)
    _, after = rest.split(END_MARKER, 1)
    README_PATH.write_text(f"{before}{BEGIN_MARKER}\n{section}\n{END_MARKER}{after}")


def main() -> None:
    records = load_all_records()
    section = render_results_section(records)
    update_readme(section)
    print(f"rendered results section from {len(records)} record(s) across {len(glob.glob(RAW_GLOB))} run file(s)")


if __name__ == "__main__":
    main()
