# graphbench

Benchmark suite comparing CognoDB Cloud against four other managed graph databases on identical
data and workloads. Take-home assignment; deliverable is a public GitHub repo. The full assignment
PDF is at `docs/assignment.pdf` — read it before any architectural decision.

## Prime directive

Never fabricate a measurement. Not as a placeholder, not as an example, not in a docstring, not in
a README table. If a platform is unreachable, a run fails, or credentials are missing: stop, write
the failure into `results/failures.md`, and tell me. A benchmark repo containing one invented
number is worthless and I will be asked to defend every figure in an interview.

Corollary: no mock adapters that return synthetic latencies. If you need a test double, name it
`FakeAdapter`, keep it in `tests/`, and make it impossible for `cli.py` to select it.

## What is being graded

| Weight | Criterion |
|---|---|
| 25% | Methodology & fairness — same data/queries, warm-up, tier parity, honest caveats |
| 20% | Completeness — every required metric on every platform |
| 20% | Reproducibility & code quality — one-command runs, pinned deps |
| 15% | README & analysis |
| 20% | Communication quality |

Implication: five platforms fully measured beats eight partially measured. Breadth is worth less
than completeness. Do not add a sixth platform until all five have every metric in section 5.2 of
the assignment.

## Hard rules

- No secrets in the repo. All credentials via env vars named in `config/platforms.yaml`. `.env` is
  gitignored. `.env.example` contains variable names and empty values only. Run `gitleaks detect`
  before every commit; wire it into `.git/hooks/pre-commit` in stage A.
- Raw records are the source of truth. Every request appends one JSONL line to
  `results/raw/<run_id>.jsonl`. Aggregation happens only in `analysis/`. Never write a summary
  statistic to disk as primary data.
- README tables are generated, not typed. `analysis/render_readme.py` reads `results/raw/*.jsonl`
  and writes the results section between `<!-- BEGIN RESULTS -->` / `<!-- END RESULTS -->` markers.
  If a number appears in the README that cannot be traced to a JSONL row, that is a bug.
- Every run is traceable. `run_id = <utc-iso>-<git-short-sha>`. Refuse to run with a dirty working
  tree unless `--allow-dirty` is passed.
- Percentiles come from merged raw samples. Never average p95s across runs. Never compute
  percentiles from pre-bucketed data.
- Adding a platform must touch exactly two files: one new `adapters/<name>.py` and one block in
  `config/platforms.yaml`. If a change requires editing a workload file to accommodate a specific
  database, the abstraction is wrong — stop and tell me instead of special-casing.

## Architecture contract

```
graphbench/
  core/
    adapter.py      Protocol: connect, close, rtt_probe_ms, create_indexes,
                    load, execute, footprint. Adapters know their database;
                    they never know what a workload is.
    record.py       Record dataclass -> JSONL. Fields include intended_start_ns,
                    actual_start_ns, queue_delay_ms, degree_band, fingerprint.
    runner.py       warmup phase + open-loop load generator
    sampler.py      degree-stratified start-node selection, fixed seed
    stats.py        percentiles from raw samples
    validate.py     cross-platform result-equality gate
  adapters/         bolt.py, falkordb.py, gremlin.py, kuzu.py, ...
  workloads/        ingest, traversal, lookup, aggregation, mixed
  dataset/          fetch, sample, manifest
analysis/           charts.py, render_readme.py
config/             platforms.yaml, workloads.yaml
docker/             compose.capped.yml  (Track B, --cpus/--memory caps)
results/raw/        *.jsonl (gitignored above 50MB; keep a sample committed)
```

Each adapter exposes `QUERIES: dict[str, str]` mapping a logical workload name to its native query
text. That dict is the only place query-language differences are allowed to live, so a reader can
audit the "same logical queries" claim in one glance.

## Measurement rules — these are the differentiators, do not skip

- **RTT floor.** Every platform gets `rtt_probe_ms()` (trivial query, 100 samples). Report all
  latencies raw and RTT-adjusted. Cross-region network time is not database time.
- **Degree stratification.** Start nodes are bucketed by degree into low (p10–p30), mid (p45–p55),
  high (p90–p99). The same node IDs are replayed on every platform. Report percentiles per band.
  Uniform random sampling produces a bimodal distribution where p95 measures how many hubs the
  sampler happened to pick — that is noise, not a result.
- **Open loop.** Load generation uses precomputed intended start times. Record
  `queue_delay_ms = actual_start - intended_start`. If queue delay trends upward, the generator fell
  behind and that run is invalid — flag it, do not publish it. Closed-loop (send → wait → send)
  systematically hides tail latency and must not be used for the mixed workload.
- **Result-equality gate.** Before any measurement, `validate.py` runs each logical query against
  every platform for 20 fixed sample nodes and compares `fingerprint` (sha256 of the canonicalised,
  sorted result set). Mismatch = abort with a diff. A Cypher query returning distinct nodes where a
  Gremlin query returns paths makes one database look 30× faster for no real reason.
- **Burst credits.** Free tiers are burstable. The mixed workload runs ≥20 minutes so a CPU-credit
  exhaustion cliff, if present, shows up in the time series. Do not truncate it to save time.
- **Two tracks.** Track A = managed free tiers as shipped (product parity, not hardware parity —
  say so). Track B = self-hosted in Docker capped to `--cpus=0.5 --memory=256m`, plus a memory sweep
  at 256/512/1024/2048 MB. Engines that OOM at 256 MB are a result, recorded as such, not a failed
  run.

## Anti-patterns — reject these if you catch yourself reaching for one

- Bar charts of mean latency. Use CDFs and percentile tables.
- `time.time()` for timing. Use `time.perf_counter_ns()`.
- Retry-on-error inside the measurement loop. Record the failure and move on.
- Swallowing exceptions. Every failure becomes a `Record` with `ok=False`.
- Warmup samples mixed into measurement. `phase` field separates them.
- Hardcoded node IDs, region names, or instance sizes outside `config/`.
- Editing README results tables by hand.

## Style

Python 3.11+. `ruff` + `mypy --strict` clean. Dataclasses over dicts for anything crossing a module
boundary. Pinned `==` requirements. Docstrings explain why, not what. No comments restating the line
below them.

## Working agreement

- Work in the stage I give you. Do not jump ahead to later stages.
- End every stage by running its gate command and showing me real output.
- Commit at each stage boundary with a message naming the stage.
- If a design decision is underdetermined by this file, ask rather than guess.
- If something in this file is wrong or in conflict with the assignment PDF, say so — the PDF wins.

## Known environment constraint (2026-08-10)

This repo has so far been developed inside a sandboxed remote session whose network egress is
restricted to GitHub and package registries. None of the five target platforms (CognoDB, Neo4j
AuraDB, Memgraph Cloud, FalkorDB Cloud, ArangoDB Oasis) nor any non-GitHub dataset host were
reachable from that session, and the Bolt protocol is not proxyable there at all (raw TCP, non-443).
Stages B through H — anything requiring a live database connection or a produced measurement — were
therefore **not executable** in that session. See `results/failures.md` for the concrete record of
what was attempted and blocked. The code for those stages is written and unit-tested against a
`FakeAdapter` confined to `tests/`, but it has never been run against a real platform. Do not treat
anything under `results/raw/` as populated until someone runs this from an environment with real
network access and real credentials in `.env`.

## Session note: this repo was rebuilt once after a container reset

Around the middle of building this out, the sandbox container reset back to an early checkpoint
(directory skeleton only) and silently dropped every uncommitted file written after that point.
Everything was reconstructed from conversation history and re-verified (dataset re-downloaded and
re-counted, sampler re-run, gitleaks hook re-installed and re-tested against a fake secret) rather
than assumed intact. If something here looks half-finished, it may be a seam from that rebuild
rather than an original design gap — check before assuming either way.
