# Failures and blockers

Per `CLAUDE.md`'s prime directive: if a platform is unreachable, a run
fails, or credentials are missing, that gets written here and reported,
never silently worked around. This file is the concrete record backing the
"Known limitations" section of the README.

## Network egress from the build environment

This repo was built inside a sandboxed remote session whose outbound HTTPS
goes through a policy-enforcing proxy. Checked directly (`curl` through the
proxy) before writing any adapter code:

| Host | Result |
|---|---|
| `console.cognodb.com` | 403 (gateway policy denial) |
| `neo4j.com` | 403 |
| `memgraph.com` | 403 |
| `falkordb.com` | 403 |
| `arangodb.com` | 403 |
| `snap.stanford.edu` | 403 |
| `files.grouplens.org` | 403 |
| `huggingface.co`, `datasets-server.huggingface.co` | 403 |
| `archive.org` | 403 |
| `zenodo.org` | 403 |
| `networkrepository.com`, `nrvis.com` | 403 |
| `raw.githack.com` | 403 |
| `github.com`, `api.github.com`, `codeload.github.com` | reachable, but scoped to this session's designated repository only (calls against other repos are rejected with an explicit "not enabled for this session" error) |
| `raw.githubusercontent.com` | reachable, unscoped - this is the one channel that worked for arbitrary public content, and is how `dataset/fetch.py` reaches the MUSAE dataset |

Consequences:

- **Stage 0 (account signup for all five platforms) could not be attempted
  from this session.** Not "attempted and failed" - genuinely not
  reachable. No accounts exist, no credentials exist, `.env` is empty by
  necessity.
- **The dataset could not be fetched from any of the assignment's suggested
  sources** (SNAP, or any non-GitHub host). `dataset/fetch.py` was pointed
  at a real, peer-reviewed, appropriately-sized dataset mirrored on GitHub
  instead (MUSAE GitHub developer network - see README's Dataset section).
  This is a documented substitution, not a silent one.
- **Even with real credentials, this session could not have connected to
  any of the five databases.** Separate from the domain-level 403s above,
  the proxy's own documentation states raw-TCP protocols and non-443 ports
  are not supported through it at all - and Bolt (`bolt+s://`, port 7687)
  is exactly that. This was confirmed against the proxy's status/readme
  output, not assumed.

Given both of the above, Stages B through H of the original working plan
(anything requiring a live database connection or a produced measurement)
were not executable in this environment. The user was informed of this
before any adapter code was written (see the session's `AskUserQuestion`
exchange) and explicitly chose "build the full code scaffold now, run it
yourself" over the alternatives (change the environment's network policy,
or stop at a smaller scaffold and wait).

## What this means concretely for the repository right now

- `results/raw/` is empty. No `Record` has ever been written by anything
  other than a unit test operating on `tests/fakes.py`'s `FakeAdapter`.
- `data/manifest.json`, `data/nodes.csv`, `data/edges.csv`, and
  `data/start_nodes.json` **are** real - `make dataset` and `make sample`
  ran successfully against the live GitHub mirror and their output was
  verified independently (line counts, SHA256) rather than trusted from a
  single tool's stdout.
- `adapters/bolt.py`, `adapters/falkordb.py`, and `adapters/arangodb.py`
  are checked against each library's actual installed method signatures
  (via `python3 -c "import ...; help(...)"`-style introspection in this
  session, not against documentation memory), but have never opened a
  socket to a real CognoDB, Neo4j AuraDB, Memgraph, FalkorDB, or ArangoDB
  instance.
- `config/platforms.yaml`'s `advertised_specs` are filled in only for
  CognoDB (quoted verbatim from `docs/assignment.pdf` §3, a primary source
  already in hand). The other four platforms' specs are `null` with a
  `source: null # TODO` marker, not a guessed number.

## Next steps (for whoever runs this with real network access)

1. Complete Stage 0: sign up for all five platforms, provision the free
   instance/trial on each, fill in `.env` from `.env.example`.
2. `make dataset && make sample` can be re-run as-is (or re-pointed at a
   SNAP-hosted graph in `dataset/fetch.py` if preferred - `dataset/sample.py`
   already handles the down-sampling case for a larger source).
3. `make load PLATFORM=<name>` / `make bench PLATFORM=<name>` for each of
   the five platforms in `config/platforms.yaml`.
4. `make validate` before trusting any of the above - this is also the
   first real-world exercise of `adapters/falkordb.py` and
   `adapters/arangodb.py` against live servers; expect to need small fixes
   to `QueryResult` parsing or AQL traversal semantics (flagged inline in
   both files' docstrings as unverified).
5. `make sweep PLATFORM=<name>` for the concurrency sweep, then `make
   report` to regenerate the README's Results section from what actually
   ran.

## Container reset during development (2026-08-10)

Partway through building this repository in the sandboxed session above,
the container silently reset to an early checkpoint - the directory
skeleton created in the first few minutes of work - and every file written
after that point (all of `graphbench/core/`, `graphbench/adapters/`,
`graphbench/dataset/`, `graphbench/workloads/`, `config/`, `analysis/`,
`cli.py`, `requirements.txt`, `Makefile`, `README.md`, most of `tests/`,
plus pip-installed dependencies and the `gitleaks` binary) was gone with no
error or warning; only the four most recently written test files survived.

Everything was reconstructed from the session's own conversation history
(the file contents had already been composed and reviewed once) and
re-verified rather than assumed intact:

- the dataset was re-fetched from GitHub and its node/relationship counts
  and SHA256 hashes re-computed independently, matching the pre-reset run
  exactly (37,700 nodes / 289,003 relationships);
- the sampler was re-run and produced the same band sizes (40/40/40 +
  20-node equality gate);
- the gitleaks pre-commit hook was reinstalled and re-tested against a
  fake AWS key, which it blocked again;
- `ruff check .`, `mypy --strict`, and `pytest -q` were all run fresh
  against the reconstructed code and are what is reported as passing in
  this repository's history, not carried over from before the reset.

The rebuild is committed in small increments (and pushed after each one)
specifically so a second reset, if it happens again, loses at most one
increment rather than the whole session's work.
