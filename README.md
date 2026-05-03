# ydbctl

A programmer/AI-friendly CLI wrapper for YottaDB Docker containers.
Hides the patchwork of `docker exec`, `mupip` / `lke` / `gde` invocations,
IPC bookkeeping, and direct-mode heredocs behind a deterministic,
JSON-first surface.

This repo implements **Phases 1, 2, and 3** of the design — read-only
floor + M execution / SQL / shell / globals + maintenance ops
(integ / reorg / freeze / locks / rundown / recover / backup / restore).
Every command is tested against a live `ydb-test` container.

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

### Phase 2 subcommands (M execution / SQL / shell / globals)

| Command | Purpose | Mechanism |
|---|---|---|
| `ydbctl exec '<m-code>'` | Run M via `yottadb -run %XCMD` | one-shot, clean output |
| `ydbctl exec --stdin` | Read M from stdin | flattened to single line |
| `ydbctl exec --file PATH` | Read M from a host file | flattened |
| `ydbctl exec --run "ENTRY^ROUTINE" [--arg X]` | Invoke a labelled entry | `yottadb -run` |
| `ydbctl exec '<m>' --direct` | Multi-line via heredoc | `yottadb -direct` + HALT injection |
| `ydbctl sql '<sql>' [--file PATH]` | SQL via Octo (when installed) | reports `not_found` if Octo missing |
| `ydbctl shell [--dry-run]` | Interactive M shell | `os.execvp` into `docker exec -it` |
| `ydbctl globals show NAME` | Dump `^NAME` subtree | guarded `IF $D(^X) ZWRITE ^X` |
| `ydbctl globals export NAME [--to PATH] [--format ZWR]` | Extract to host file | `mupip extract` + `docker cp` |

Phase 2 design notes vs irisctl:

- **No license bookkeeping.** YottaDB is Apache 2.0 with no LU concept,
  so no precheck, no `--force` flag for license bypass, no retry on
  `<LICENSE LIMIT EXCEEDED>`. Each call just runs.
- **Dual execution paths.** `%XCMD` is the default (clean stdout, no
  `YDB>` prompts). `--direct` switches to the heredoc path for
  multi-line scripts that can't fit on one logical M line.
- **`ZWRITE` not `ZW`.** The `ZW` abbreviation produced no output in
  r2.07 — the wrapper uses the full keyword.
- **`mupip extract` won't overwrite.** The wrapper `rm -f`s the
  in-container target before extracting.

Examples:

```bash
$ ydbctl exec 'W $ZV,!' --human
mode    xcmd
output  GT.M V7.1-002 Linux x86_64

$ ydbctl exec --direct '\nS A=2\nS B=3\nW A+B,!'
{"v":1,"ok":true,"command":"exec","data":{"mode":"direct","output":"\n5\n"},"warnings":[]}

$ ydbctl globals show ^DOESNOTEXIST --human
name   ^DOESNOTEXIST
lines  []
count  0
note   global has no defined nodes

$ ydbctl shell --dry-run --human
argv     ['docker', 'exec', '-it', 'ydb-test', 'bash', '-c',
          '. /opt/yottadb/current/ydb_env_set >/dev/null 2>&1 && exec yottadb -direct']
dry_run  yes
```

### Phase 3 subcommands (maintenance — the operationally interesting ones)

| Command | Purpose | Mechanism |
|---|---|---|
| `ydbctl integ [--region R] [--full]` | Integrity check + per-region pass/fail summary | `mupip integ -fast/-full` |
| `ydbctl reorg [--region R] [--truncate]` | Defrag/coalesce blocks | `mupip reorg` |
| `ydbctl freeze --on/--off [--region R]` | Suspend/resume DB updates | `mupip freeze -on/-off <region>` |
| `ydbctl locks show [--region R]` | View active M LOCKs | `lke show -all` |
| `ydbctl locks clear --yes [--region R]` | Clear M LOCKs (mutating, --yes-gated) | `lke clear -all -nointeractive` |
| `ydbctl rundown [--region R]` | Release orphan IPC after unclean shutdown | `mupip rundown -region <r>` |
| `ydbctl recover [--region R] [--journal-file F] [--forward]` | Replay journal records | `mupip journal -recover -backward` |
| `ydbctl backup [REGION] [--to PATH] [--offline]` | Bytestream backup → host file | `mupip backup -bytestream` + `docker cp` |
| `ydbctl restore --from F --target DAT --yes` | Overwrite DAT from backup (destructive) | `docker cp` + `mupip restore` |

Phase 3 specifics worth knowing:

- **`mupip` writes to stderr.** The wrapper merges `2>&1` inside the
  container so callers see the informational messages (`BACKUPDBFILE`,
  `MUFILRNDWNSUC`, etc.) that mupip emits there.
- **`mupip restore` enforces TN-alignment.** A backup-then-restore
  in the same session generally fails with `MUPRESTERR` because the
  backup itself advances the DB's transaction number. The wrapper
  surfaces the error cleanly; this is mupip's contract, not a bug.
- **`mupip backup` refuses to overwrite.** The wrapper `rm -f`s the
  in-container target before invoking — same trick as
  `globals export`.
- **`freeze` uses positional region** (no `-region` flag), unlike
  most other mupip subcommands. The wrapper hides this asymmetry.
- **`mupip rundown` returns non-zero on missing `.repl`** in
  non-replicated installs — the wrapper detects the FILENOTFND
  noise, surfaces it as a warning, and still reports success when
  per-region rundowns succeeded.

Examples:

```bash
$ ydbctl integ --human | head -8
mode             fast
region_arg       *
regions_checked  4
all_ok           yes
regions          [{'region': 'DEFAULT', 'ok': True}, ...]

$ ydbctl backup --to ~/data/backups/ydb --human
region          DEFAULT
host_path       /home/rafael/data/backups/ydb/default.bk
size_bytes      4331520
online          yes
container_path  /tmp/ydbctl-backup-default.bk
db_files        [{'db_file': '/data/r2.07_x86_64/g/yottadb.dat',
                  'backup_file': '/tmp/ydbctl-backup-default.bk'}]

$ ydbctl freeze --on --region DEFAULT --human
action            on
region_arg        DEFAULT
regions_affected  1
regions           [{'region': 'DEFAULT', 'state': 'FROZEN'}]

$ ydbctl restore --from /backup.bk --target /data/x.dat --dry-run
{"v":1,"ok":true,"command":"restore","data":{...,"dry_run":true,
 "steps":["docker cp /backup.bk ydb-test:/tmp/ydbctl-restore-source.bk",
          "mupip restore /data/x.dat /tmp/ydbctl-restore-source.bk"]}}
```

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

After Phase 3: **107 passed + 1 deselected** (~9.3s).

- 21 unit tests on parsers + output + config envelope
- 86 integration tests against the live container
- 1 `@slow` test (real backup → restore round-trip) opt-in via
  `make test-slow`
- Default coverage: ~44% (gate at 25%).

## Roadmap

| Phase | Subcommands | Status |
|---|---|---|
| 1 | status, version, ports, env, regions, files, dbinfo, ipc, logs, health, which | **shipped** |
| 2 | exec, sql (via Octo when installed), shell, globals show/export | **shipped** |
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
