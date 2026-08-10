#!/usr/bin/env python3
"""Single entry point wiring every Makefile target to real adapters only.

FakeAdapter (tests/fakes.py) is never imported here - by construction, not
convention, since this module never imports anything from the tests/
package. build_adapter() is the only function that turns a platform name
into a live Adapter, and every branch in it constructs a concrete class
from graphbench/adapters/.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from graphbench.core.adapter import Adapter
from graphbench.core.record import Record
from graphbench.core.runner import run_open_loop, run_read_workload
from graphbench.core.sampler import StartNodes
from graphbench.core.stats import group_by, summarize_records
from graphbench.core.validate import format_diff, run_equality_gate
from graphbench.workloads import aggregation, lookup, mixed, traversal
from graphbench.workloads import ingest as ingest_workload

PLATFORMS_CONFIG = Path("config/platforms.yaml")
WORKLOADS_CONFIG = Path("config/workloads.yaml")
RESULTS_RAW_DIR = Path("results/raw")


def _load_yaml(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(path.read_text())
    return data


def _git_short_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def _is_dirty() -> bool:
    result = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, check=True)
    return bool(result.stdout.strip())


def make_run_id() -> str:
    return f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{_git_short_sha()}"


def _require_clean_tree(allow_dirty: bool) -> None:
    if not allow_dirty and _is_dirty():
        raise SystemExit(
            "refusing to run with a dirty working tree (run_id embeds the git sha and "
            "would not be reproducible) - commit your changes or pass --allow-dirty"
        )


def _require_env(var_name: str) -> str:
    value = os.environ.get(var_name)
    if not value:
        raise RuntimeError(
            f"environment variable {var_name} is not set - copy .env.example to .env, fill in "
            "real credentials from Stage 0, and export them before running graphbench"
        )
    return value


def build_adapter(platform_name: str) -> Adapter:
    config = _load_yaml(PLATFORMS_CONFIG)["platforms"][platform_name]
    adapter_type = config["adapter"]
    conn = config["connection"]

    if adapter_type == "bolt":
        from graphbench.adapters.bolt import BoltAdapter

        database_env = conn.get("database_env")
        return BoltAdapter(
            uri=_require_env(conn["uri_env"]),
            user=_require_env(conn["user_env"]),
            password=_require_env(conn["password_env"]),
            database=(os.environ.get(database_env) or None) if database_env else None,
        )
    if adapter_type == "falkordb":
        from graphbench.adapters.falkordb import FalkorDBAdapter

        password_env = conn.get("password_env")
        return FalkorDBAdapter(
            host=_require_env(conn["host_env"]),
            port=int(_require_env(conn["port_env"])),
            password=(os.environ.get(password_env) or None) if password_env else None,
            graph_name=_require_env(conn["graph_name_env"]),
        )
    if adapter_type == "arangodb":
        from graphbench.adapters.arangodb import ArangoDBAdapter

        return ArangoDBAdapter(
            url=_require_env(conn["url_env"]),
            user=_require_env(conn["user_env"]),
            password=_require_env(conn["password_env"]),
            database=_require_env(conn["database_env"]),
        )
    raise ValueError(f"unknown adapter type {adapter_type!r} for platform {platform_name!r}")


def _write_records(records: list[Record], run_id: str) -> Path:
    RESULTS_RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_RAW_DIR / f"{run_id}.jsonl"
    with path.open("a") as f:
        for record in records:
            f.write(record.to_jsonl() + "\n")
    return path


def _load_start_nodes() -> StartNodes:
    dataset_config = _load_yaml(WORKLOADS_CONFIG)["dataset"]
    data = json.loads(Path(dataset_config["start_nodes"]).read_text())
    return StartNodes(**data)


def cmd_dataset(args: argparse.Namespace) -> None:
    from graphbench.dataset.build import main as build_main

    build_main()


def cmd_sample(args: argparse.Namespace) -> None:
    from graphbench.core.sampler import main as sample_main

    sample_main()


def cmd_load(args: argparse.Namespace) -> None:
    _require_clean_tree(args.allow_dirty)
    run_id = make_run_id()
    dataset_config = _load_yaml(WORKLOADS_CONFIG)["dataset"]
    batch_size = _load_yaml(WORKLOADS_CONFIG)["ingest"]["batch_size"]

    adapter = build_adapter(args.platform)
    adapter.connect()
    try:
        outcome = ingest_workload.run_ingest(
            adapter, Path(dataset_config["nodes_csv"]), Path(dataset_config["edges_csv"]), batch_size
        )
    finally:
        adapter.close()

    record = Record(
        run_id=run_id,
        platform=args.platform,
        workload="ingest",
        phase="measure",
        ok=True,
        actual_start_ns=0,
        end_ns=int(outcome.load_result.wall_clock_ms * 1e6),
        latency_ms=outcome.load_result.wall_clock_ms,
        node_count=outcome.load_result.node_count,
        relationship_count=outcome.load_result.relationship_count,
    )
    path = _write_records([record], run_id)

    nodes_per_sec = outcome.load_result.node_count / (outcome.load_result.wall_clock_ms / 1000)
    rels_per_sec = outcome.load_result.relationship_count / (outcome.load_result.wall_clock_ms / 1000)
    print(f"wrote {path}")
    print(f"nodes/sec={nodes_per_sec:.1f} relationships/sec={rels_per_sec:.1f}")
    print(f"indexes: {outcome.indexes_created}")


def cmd_bench(args: argparse.Namespace) -> None:
    _require_clean_tree(args.allow_dirty)
    run_id = make_run_id()
    config = _load_yaml(WORKLOADS_CONFIG)
    read_config = config["read_workloads"]
    start_nodes = _load_start_nodes()

    adapter = build_adapter(args.platform)
    adapter.connect()
    all_records: list[Record] = []
    try:
        rtt_samples = adapter.rtt_probe_ms(samples=config["rtt_probe"]["samples"])
        all_records.extend(
            Record(
                run_id=run_id,
                platform=args.platform,
                workload="rtt_probe",
                phase="measure",
                ok=True,
                actual_start_ns=0,
                end_ns=int(latency * 1e6),
                latency_ms=latency,
            )
            for latency in rtt_samples
        )

        param_builders: dict[str, Callable[[str], dict[str, Any]]] = {
            **{name: traversal.param_builder for name in traversal.WORKLOAD_NAMES},
            **lookup.PARAM_BUILDERS,
        }
        for workload in read_config["workloads"]:
            if workload in aggregation.WORKLOAD_NAMES:
                continue  # whole-graph, not degree-band-parameterized; see below
            for band, node_ids in start_nodes.nodes_per_band.items():
                all_records.extend(
                    run_read_workload(
                        adapter,
                        args.platform,
                        run_id,
                        workload,
                        band,  # type: ignore[arg-type]
                        node_ids,
                        read_config["warmup_iterations"],
                        read_config["measured_iterations"],
                        param_builders[workload],
                    )
                )

        for workload in aggregation.WORKLOAD_NAMES:
            all_records.extend(
                run_read_workload(
                    adapter,
                    args.platform,
                    run_id,
                    workload,
                    "mid",  # whole-graph query, band is not meaningful  # type: ignore[arg-type]
                    ["<whole-graph>"],
                    read_config["warmup_iterations"],
                    read_config["measured_iterations"],
                    lambda _node_id: {},
                )
            )
    finally:
        adapter.close()

    path = _write_records(all_records, run_id)
    print(f"wrote {len(all_records)} records to {path}")

    for group_key, records in sorted(group_by(all_records, "workload", "degree_band").items()):
        measured = [r for r in records if r.phase == "measure" and r.ok]
        if not measured:
            continue
        summary = summarize_records(records)
        print(f"{group_key}: n={summary.count} p50={summary.p50_ms:.2f}ms p95={summary.p95_ms:.2f}ms")


def cmd_validate(args: argparse.Namespace) -> None:
    _require_clean_tree(args.allow_dirty)
    platforms = _load_yaml(PLATFORMS_CONFIG)["platforms"]
    start_nodes = _load_start_nodes()

    adapters: dict[str, Adapter] = {}
    for name in platforms:
        adapter = build_adapter(name)
        adapter.connect()
        adapters[name] = adapter

    try:
        node_parameterized: dict[str, Callable[[str], dict[str, Any]]] = {
            **{name: traversal.param_builder for name in traversal.WORKLOAD_NAMES},
            **lookup.PARAM_BUILDERS,
        }
        result = run_equality_gate(
            adapters,
            node_parameterized,
            aggregation.WORKLOAD_NAMES,
            start_nodes.equality_gate_nodes,
        )
    finally:
        for adapter in adapters.values():
            adapter.close()

    print(format_diff(result))
    if not result.ok:
        raise SystemExit(1)


def cmd_sweep(args: argparse.Namespace) -> None:
    _require_clean_tree(args.allow_dirty)
    run_id = make_run_id()
    config = _load_yaml(WORKLOADS_CONFIG)
    mixed_config = config["mixed_workload"]
    sampling_config = config["sampling"]
    start_nodes = _load_start_nodes()

    node_ids = sorted({n for nodes in start_nodes.nodes_per_band.values() for n in nodes})
    all_records: list[Record] = []

    for concurrency in mixed_config["concurrency_sweep"]:
        picker = mixed.make_picker(node_ids, mixed_config["read_write_ratio"], seed=sampling_config["seed"])
        result = run_open_loop(
            adapter_factory=lambda: build_adapter(args.platform),
            platform=args.platform,
            run_id=run_id,
            workload_picker=picker,
            concurrency=concurrency,
            duration_seconds=mixed_config["duration_seconds"],
            intended_qps_per_client=mixed_config["intended_qps_per_client"],
        )
        all_records.extend(result.records)

        ok_count = sum(1 for r in result.records if r.ok)
        qps = ok_count / mixed_config["duration_seconds"]
        print(
            f"concurrency={concurrency} sustained_qps={qps:.1f} "
            f"queue_delay_trend_ms_per_min={result.queue_delay_trend_ms_per_min:.3f}"
        )
        max_slope = mixed_config["queue_delay_trend_max_slope_ms_per_min"]
        if result.queue_delay_trend_ms_per_min > max_slope:
            print(
                f"INVALID RUN: queue delay trended upward faster than {max_slope} ms/min - "
                "the generator fell behind the database, not the other way around. Do not "
                "publish this concurrency level's numbers.",
                file=sys.stderr,
            )

    path = _write_records(all_records, run_id)
    print(f"wrote {len(all_records)} records to {path}")


def cmd_report(args: argparse.Namespace) -> None:
    from analysis.render_readme import main as render_main

    render_main()


def main() -> None:
    parser = argparse.ArgumentParser(prog="graphbench")
    sub = parser.add_subparsers(dest="command", required=True)

    for name, fn in [
        ("dataset", cmd_dataset),
        ("sample", cmd_sample),
        ("report", cmd_report),
    ]:
        p = sub.add_parser(name)
        p.set_defaults(func=fn)

    for name, fn in [
        ("load", cmd_load),
        ("bench", cmd_bench),
        ("validate", cmd_validate),
        ("sweep", cmd_sweep),
    ]:
        p = sub.add_parser(name)
        p.add_argument("--platform", required=(name != "validate"))
        p.add_argument("--allow-dirty", action="store_true")
        p.set_defaults(func=fn)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
