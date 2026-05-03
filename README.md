# ydbctl

A programmer/AI-friendly CLI wrapper for YottaDB Docker containers.
Hides the patchwork of `docker exec`, `mupip` / `lke` / `gde` invocations,
IPC bookkeeping, and direct-mode heredocs behind a deterministic,
JSON-first surface.

This repo implements **Phase 1** of the design — the read-only floor:
no IPC mutation, no auth required, every command tested against a
live `ydb-test` container.

Sibling project: [`irisctl`](https://github.com/rafael5/irisctl) for
the IRIS Community Edition Docker container — same envelope shape,
same subcommand naming where concepts overlap. See
[docs/mctl-composite.md](docs/mctl-composite.md) for the
side-by-side comparison.

## What's in here

```
ydbctl/
├── docs/
│   ├── ydb-cli-surface.md    # YottaDB CLI/API surface reference
│   ├── ydb-cli-plan.md       # 5-phase implementation plan
│   └── mctl-composite.md     # irisctl ↔ ydbctl comparison
├── src/ydbctl/
│   ├── cli.py                # argparse tree + dispatch + global flags
│   ├── output.py             # JSON envelope + human-table renderer
│   ├── docker_api.py         # docker inspect / exec / ports / wait_for_tcp
│   ├── ydb_exec.py           # docker exec + ydb_env_set sourcing
│   ├── config.py             # profiles + env-var overrides + TOML
│   ├── parsers/
│   │   ├── dumpfhead.py      # `mupip dumpfhead -file <dat>` → JSON
│   │   └── version.py        # `yottadb -version` → JSON
│   └── commands/             # one module per subcommand
└── tests/                    # 58 tests, ~29% coverage
```

## Install

```bash
make install     # uv sync + pre-commit hooks
```

## Bring up the test container

The integration tests need a live `ydb-test` container:

```bash
mkdir -p ~/data/ydb-test
docker run --name ydb-test -d \
  -v ~/data/ydb-test:/data \
  -p 9080:9080 -p 9081:9081 \
  yottadb/yottadb-base:latest-master \
  bash -c 'source /opt/yottadb/current/ydb_env_set && tail -f /dev/null'
```

After first launch, `~/data/ydb-test/r2.07_x86_64/g/` holds the
default `yottadb.dat` / `yottadb.gld` plus plugin databases
(`%ydbocto.dat`, `%ydbaim.dat`).

## Use

All commands emit a versioned JSON envelope by default. Add `--human`
for a table; `--pretty` indents JSON.

```bash
$ ydbctl status --human
container    {'status': 'running', 'running': True, ...}
ydb_release  r2.07
listeners    [{'role': 'ydb_gui', 'host_port': 9080, 'reachable': True}, ...]
ipc          {'shared_memory': [], 'semaphores': [], 'shm_count': 0, 'sem_count': 0}

$ ydbctl regions --human
container  ydb-test
regions    ['DEFAULT', 'YDBAIM', 'YDBJNLF', 'YDBOCTO']
count      4
globals    [{'global': '%ydbAIM*', 'region': 'YDBAIM'}, ...]

$ ydbctl dbinfo --human
block_size_bytes          4096
total_blocks              10020
free_blocks               9998
transaction_number        0x0000000000000001
access_method             MM
fully_upgraded            yes
file                      /data/r2.07_x86_64/g/yottadb.dat
```

### Phase 1 subcommands (all implemented + tested)

| Command | Purpose | Mechanism |
|---|---|---|
| `ydbctl status` | Composite container + version + IPC + listeners | aggregates the below |
| `ydbctl version` | YottaDB engine + image labels | `yottadb -version` |
| `ydbctl ports` | Optional service-port reachability table | `docker inspect` + TCP probe |
| `ydbctl env [NAME]` | Show ydb_*/gtm* env vars in container | `env` after `ydb_env_set` |
| `ydbctl regions` | List M regions via `gde show` | `mumps -run GDE` |
| `ydbctl files` | Enumerate `.gld` / `.dat` / `.mjl` / `.repl` | `find $ydb_dir -type f ...` |
| `ydbctl dbinfo [REGION] [--full]` | `mupip dumpfhead` summary | `mupip dumpfhead` + parser |
| `ydbctl ipc` | Shared memory + semaphore inventory | `ipcs -m`/`-s` |
| `ydbctl logs [--tail N]` | Recent journal records | `mupip journal -show -backward` |
| `ydbctl health` | Green/yellow verdict with check breakdown | composite |
| `ydbctl which [OP]` | Explain underlying mechanism | static registry |

Every command is tested end-to-end against the live `ydb-test`
container — per the project plan, "real container only — no mocking."

### Global flags (work before *or* after the subcommand)

| Flag | Effect |
|---|---|
| `--profile NAME` | Select a profile from `~/.config/ydbctl/config.toml` |
| `--json` | JSON output (default) |
| `--human` | Render as a human-readable table |
| `--pretty` | Pretty-print JSON output |

### Configuration

Default profile points at `ydb-test` container on `localhost`.
Override via env vars (`YDBCTL_PROFILE`, `YDBCTL_CONTAINER`,
`YDBCTL_HOST`, `YDBCTL_DATA_DIR`, `YDBCTL_YDB_DIST`) or via
`~/.config/ydbctl/config.toml`:

```toml
default_profile = "ydb-test"

[profiles.ydb-test]
container = "ydb-test"
host = "127.0.0.1"
data_dir = "~/data/ydb-test"
ydb_dist = "/opt/yottadb/current"
```

## Output contract (mirrors irisctl)

```json
{"v": 1, "ok": true, "command": "regions", "data": {...}, "warnings": []}
{"v": 1, "ok": false, "command": "ipc",
 "error": {"code": "ipc_orphans", "message": "...",
           "hint": "...", "ref": "..."}}
```

Stable error codes ↔ exit codes:

| Code | Exit | Notes |
|---|---|---|
| `ok` | 0 | |
| `internal` | 1 | |
| `usage` | 2 | |
| `instance_not_running` | 3 | |
| `ipc_orphans` | 4 | **YottaDB-specific** — replaces IRIS's `license_exhausted` |
| `auth_required` / `auth_failed` | 5 | |
| `not_found` | 6 | |
| `ydb_error` | 7 | |
| `docker_error` | 8 | |
| `network_error` | 9 | |

## Testing approach

Per the plan: **real container only — no mocking**. Every command's
behavior is verified end-to-end against a live `ydb-test` YottaDB
container.

```bash
make test         # full suite: 58 tests, ~4 seconds
make test-unit    # parser + envelope unit tests only — no container needed
make test-int     # integration tests against live ydb-test container
make watch        # TDD mode: re-run on file save
make cov          # coverage report (gate: 25%)
make check        # lint + mypy + cov (full gate)
```

The `live_ydb` pytest fixture is the readiness probe — tests marked
`@pytest.mark.integration` skip cleanly if the container isn't up.

### Test totals

After Phase 1: **58 passed** (~4.2s).

- ~10 unit tests on parsers + output envelope
- ~38 integration tests against the live container
- Default coverage: ~29% (gate at 25%; subprocess tracing is the
  bottleneck — Phase 2 direct-import tests would push past 70%).

## Roadmap

| Phase | Subcommands | Status |
|---|---|---|
| 1 | status, version, ports, env, regions, files, dbinfo, ipc, logs, health, which | **shipped** |
| 2 | exec, sql (via Octo/ROcto), shell, globals show/export | not started |
| 3 | maintenance: backup, restore, integ, reorg, freeze, locks, rundown, recover | not started |
| 4 | services: gui, rocto, web, gtcm + VistA layer if `profile.vista=true` | not started |
| 5 | replication, polish | not started (pipx packaging skipped) |

See [docs/ydb-cli-plan.md](docs/ydb-cli-plan.md) for the full
proposal, including LOC estimates and the cross-tool design contract
with the parallel `irisctl` wrapper.

## Architectural note: YottaDB is a library, not a daemon

Unlike IRIS where one daemon manages everything, YottaDB processes
attach to shared memory and `.dat` files directly via `mmap` + System
V IPC. This shapes ydbctl's design:

- Every subcommand sources `ydb_env_set` first (the canonical way to
  set `ydb_dist`, `ydb_routines`, `ydb_gbldir`, etc.).
- `ipc` exposes the shared-memory + semaphore state directly because
  there's no daemon abstracting it away.
- Phase 3 will need explicit `rundown` / `recover` commands because
  YottaDB has no equivalent of `iris start`'s implicit recovery.
- License/LU concerns from `irisctl` simply don't exist here —
  YottaDB is Apache 2.0 with no per-process budget.

## License

Internal / personal — not licensed for external use yet.
