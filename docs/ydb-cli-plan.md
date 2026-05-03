# `ydbctl` — Proposal & Implementation Plan

A unified CLI wrapper that hides the patchwork of `docker exec`,
`mupip` / `lke` / `gde` / `dse` invocations, IPC bookkeeping, journal
recovery, and direct-mode heredocs behind one deterministic, JSON-first
surface — designed so an AI agent can drive a YottaDB Docker
container without re-discovering [the surface](ydb-cli-surface.md) on
every task.

This is a proposal, not an implementation. Companion documents:
[ydb-cli-surface.md](ydb-cli-surface.md) (the surface this wraps),
[iris-cli-plan.md](iris-cli-plan.md) (the parallel design for IRIS).

---

## 1. Goal

When an AI agent (or programmer) asks "is the DB OK", "what regions
exist", "back up the database", "tail the journal", or "run this M
routine", the path to an answer should be a single subcommand — not a
per-task decision tree about which of `mupip`, `lke`, `gde`, `dse`,
`yottadb -direct`, or `docker exec` to use.

**Concrete pain the wrapper fixes:**

| Today | With `ydbctl` |
|---|---|
| `docker exec -i ydb yottadb -direct <<'END' … HALT END` plus remembering `HALT` not `QUIT` | `ydbctl exec '…'` |
| `docker exec ydb mupip dumpfhead -file /data/yottadb.dat` for each region | `ydbctl dbinfo` |
| Forgetting `mupip rundown -region "*"` after `docker kill` | `ydbctl status` flags orphan IPC; `ydbctl rundown` clears it |
| Pasting the right `mupip backup -bytestream -online "*" /backup/` | `ydbctl backup` |
| `docker exec ydb gde <<'END' SHOW END` to see regions | `ydbctl regions` |
| Hand-editing `.gld` files (which silently corrupts) | `ydbctl config merge file.gde` |
| Running `lke show -all` to find a stuck lock | `ydbctl locks show` |
| Knowing whether to use Octo or ROcto for SQL | `ydbctl sql` (auto-routes) |
| Wondering why `docker stop` left orphan SHM | `ydbctl stop` defaults to `-t 60`, runs rundown post-shutdown |

---

## 2. How this differs from `irisctl`

The IRIS wrapper had an HTTP-first / exec-last hierarchy: most reads
were free `/api/monitor/metrics` calls. **YottaDB has no equivalent
HTTP surface in the base image** — every read goes through `mupip` /
`gde` / `lke` subprocesses inside the container.

| Concern | IRIS path | YottaDB path |
|---|---|---|
| Live metrics | `GET /api/monitor/metrics` (no LU) | `mupip dumpfhead`, `mupip integ -fast`, `$VIEW()` via `yottadb -direct` (subprocess + IPC attach) |
| License management | LU pre-check before exec | **N/A** — Apache 2.0, no per-process budget |
| Source CRUD | `/api/atelier/v6` REST | `docker cp` + `yottadb -run "ZL^routine"` |
| Single instance manager | `iris start/stop/...` | `mupip` + `lke` + `gde` (binary-per-task) |
| Crash recovery | `iris start` runs auto-recovery | `mupip journal -recover -backward` + `mupip rundown -region "*"` (manual) |
| Auth | `_SYSTEM`/`SYS` default | none in core; per-protocol at GUI/ROcto/Web |
| Container shutdown | `iris-main` traps SIGTERM, runs `iris stop` | `docker-main-startup.sh` traps, runs `mupip rundown` |

The wrapper's job description shifts: less "network-to-API mapping",
more "subprocess orchestration with IPC bookkeeping". Where vanilla
YottaDB has no metrics endpoint, we expose `$VIEW()` and `dumpfhead`
output as structured JSON; if the user has the YDB GUI running,
`ydbctl` will route through its web server endpoints instead.

---

## 3. Design principles

1. **One tool, one binary, no plugins.** All under `ydbctl <verb>`.
   Sub-verbs nest one level deep.
2. **JSON-first output.** Default stdout is a versioned envelope.
   `--human` switches to tables.
3. **Idempotent where possible.** `restart` is `stop+start`.
   `rundown` is safe to call when there's nothing to clean.
4. **Service-first, exec-last.** Every operation prefers the cheapest
   path:
   - **Service path:** if YDB Web Server / GUI is running, route reads
     through `/api/version`, `/api/ping`, GUI's stats page on 9081.
   - **Exec path:** otherwise, `docker exec` the relevant `mupip` /
     `gde` / `lke` invocation.
   The wrapper auto-probes once per session and caches.
5. **IPC-aware.** Every subcommand starts with a one-line IPC orphan
   check (`mupip ftok -nohead -only` is fast and read-only). If
   orphans are detected, a structured warning is added to the output;
   `ydbctl status` shows the full picture.
6. **Stateless by default.** No long-running daemon. State lives in
   the YottaDB instance and an optional config file.
7. **Single-instance assumption, multi-region ready.** Default target
   is one container; `--region` and `--gld` flags select among
   multiple regions/global directories within that instance.
8. **Profiles for VistA layer.** When the container is the
   docker-vista-fork YottaDB build, a `vista` profile unlocks
   `ydbctl vista rpcbroker/vistalink/hl7` subcommands.
9. **Unsurprising error envelope.** Every error has a stable code, a
   human message, and a hint pointing at the surface doc.

---

## 4. Subcommand inventory

Grouped by mechanism. Every subcommand emits the standard JSON
envelope (§5) unless `--human` is given.

### 4.1 Inspection / health (no mutation)

| Subcommand | Wraps | Why it exists |
|---|---|---|
| `ydbctl status` | `docker inspect` + IPC scan + gtmsecshr probe + `mupip integ -fast` | "Is everything OK in one shot." Returns container state, IPC orphans, gtmsecshr socket, region list, journal state, `version`. |
| `ydbctl version` | `yottadb -version` + plugin probes | YottaDB build, plugin versions, image labels. |
| `ydbctl ports` | `docker inspect` + TCP probe via host-network helper | Per-port state: which of 9080/9081/1337 / VistA listeners are listening. |
| `ydbctl logs [--syslog] [--journal] [--tail N] [--follow]` | `journalctl --unit=...`, `mupip journal -show`, root-helper file reads | Three log surfaces: container syslog (gtmsecshr), `mupip journal -show` for `*.mjl`, container stdout. |
| `ydbctl env [NAME]` | reads container env via `docker exec env` | Filter to `ydb_*` / `gtm*` only by default. |
| `ydbctl health` | runs `status` + `ports` + IPC scan + journal-recoverable check | Composite "should I worry". Exits non-zero if anything red. |

### 4.2 IPC / rundown (mutating, recovery)

| Subcommand | Wraps |
|---|---|
| `ydbctl ipc` | `ipcs(1)` + `mupip ftok -nohead -only` for each region. JSON list of SHM/SEM keys with PID owners. |
| `ydbctl rundown [--region '*']` | `mupip rundown -region "*"`. Idempotent. Required after `docker kill`. |
| `ydbctl recover [--region '*']` | `mupip journal -recover -backward "*.mjl"`. Run before rundown if journal state is dirty. |

### 4.3 Regions & files (read-only)

| Subcommand | Wraps |
|---|---|
| `ydbctl regions` | `gde show -region` parsed into JSON |
| `ydbctl segments` | `gde show -segment` parsed |
| `ydbctl globals` | `gde show -name` — list which globals map to which region |
| `ydbctl files` | enumerate `.dat`/`.gld`/`.mjl`/`.repl` under `gtmdir` |
| `ydbctl dbinfo [REGION]` | `mupip dumpfhead -file <dat>` parsed into JSON: block size, free space, journal state, transaction num, etc. |

### 4.4 Journal (read + mutate)

| Subcommand | Wraps |
|---|---|
| `ydbctl journal status [--region R]` | `mupip journal -show` |
| `ydbctl journal verify [--region R]` | `mupip journal -verify` |
| `ydbctl journal extract --to PATH` | `mupip journal -extract` |
| `ydbctl journal enable [--region R]` | `mupip set -journal=enable,on` |
| `ydbctl journal disable [--region R]` | `mupip set -journal=disable` |
| `ydbctl journal rotate [--region R]` | `mupip set -journal=on,filename=...` (new jnl file) |

### 4.5 Backup / restore (mutating)

| Subcommand | Wraps |
|---|---|
| `ydbctl backup [--to PATH] [--online]` | `mupip backup -bytestream [-online] "*" PATH`. Default `--online`; `--to` defaults to `~/data/backups/ydb-<UTC>/`. |
| `ydbctl restore --from PATH` | `mupip restore -extend PATH yottadb.dat`. Confirmation prompt unless `--yes`. |
| `ydbctl extract REGION [--format Z]` | `mupip extract -format=Z -region=R out.zwr`. |
| `ydbctl load FILE` | `mupip load FILE`. |

### 4.6 Integrity / maintenance (read-or-mutate)

| Subcommand | Wraps |
|---|---|
| `ydbctl integ [--region R] [--full]` | `mupip integ -fast` (default) or `-full`. Output parsed. |
| `ydbctl reorg [--region R] [--truncate]` | `mupip reorg`. |
| `ydbctl freeze [--on\|--off]` | `mupip freeze -on/-off "*"`. |
| `ydbctl extend REGION --blocks N` | `mupip extend -blocks=N -region=R`. |

### 4.7 Locks (read + mutate)

| Subcommand | Wraps |
|---|---|
| `ydbctl locks show [--region R] [--pid P]` | `lke show -all` parsed. |
| `ydbctl locks clear [--lock NAME] [--pid P] [--yes]` | `lke clear -interactive=N`. |
| `ydbctl locks cleanup` | `lke clnup`. |

### 4.8 Execute (M / SQL)

| Subcommand | Wraps |
|---|---|
| `ydbctl exec '<m-code>' [--region R]` | `yottadb -direct` heredoc. Auto-appends `HALT`. |
| `ydbctl exec --stdin [--region R]` | reads M from stdin |
| `ydbctl exec --file foo.m` | `docker cp` + `yottadb -run` |
| `ydbctl exec --run "MAIN^routine" [args...]` | `yottadb -run "MAIN^routine" args` |
| `ydbctl sql '<sql>' [--writes]` | Routes: ROcto if running on 1337 (`psql` wire), else `octo` CLI subprocess. `--writes` is a no-op if ROcto already has `-w`. |
| `ydbctl sql --file schema.sql` | bulk DDL |
| `ydbctl shell [--region R]` | `docker exec -it … yottadb -direct`. Pure pass-through. |

### 4.9 Globals & routines

| Subcommand | Wraps |
|---|---|
| `ydbctl globals export NAME [--format Z]` | `mupip extract -select=^NAME` |
| `ydbctl globals show NAME` | `yottadb -direct` heredoc with `ZW ^NAME` |
| `ydbctl routines list [PATTERN]` | enumerate `.m` files in `ydb_routines` paths |
| `ydbctl routines get NAME` | `docker cp` from container |
| `ydbctl routines put` (stdin or `--file`) | `docker cp` to container; recompile via `yottadb -direct` |
| `ydbctl routines compile [PATTERN]` | `yottadb -direct` `ZL pattern ZS` |

### 4.10 Lifecycle (mutating, container-level)

| Subcommand | Wraps |
|---|---|
| `ydbctl start` | `docker start NAME`. Waits for gtmsecshr socket. |
| `ydbctl stop [--timeout 60]` | `docker stop -t N NAME`. Default 60s — the 10s default is too short for `mupip rundown`. |
| `ydbctl restart` | stop + start. |
| `ydbctl recreate` | `docker rm -f` + `docker run` per the docker-vista build args. |

### 4.11 Optional services (mutating)

These manage the lifecycle of `%ydbgui`, `%ydbwebreq`, `rocto`,
`gtcm_gnp_server` — none of which auto-start in the base image.

| Subcommand | Wraps |
|---|---|
| `ydbctl gui start [--port N] [--readwrite]` | `yottadb -run %ydbgui --port N` in background |
| `ydbctl gui stop` | signal the GUI process |
| `ydbctl gui status` | probe `/api/ping` on the GUI port |
| `ydbctl rocto start [--port 1337] [--writes] [--ddl]` | `rocto -p 1337 [-w] [-a]` |
| `ydbctl rocto stop` | signal |
| `ydbctl web start [--port 9080]` | `yottadb -run start^%ydbwebreq` |
| `ydbctl web stop` | signal |
| `ydbctl gtcm start [--port 6789]` | `gtcm_gnp_server -log=GTCM.log -service=N` |
| `ydbctl gtcm stop` | signal |

### 4.12 VistA layer (only when profile is docker-vista-fork's YottaDB build)

| Subcommand | Wraps |
|---|---|
| `ydbctl vista rpcbroker [start\|stop\|status]` | `GTM/bin/rpcbroker.sh` |
| `ydbctl vista vistalink [start\|stop\|status]` | `GTM/bin/vistalink.sh` |
| `ydbctl vista hl7 [start\|stop\|status]` | `GTM/bin/hl7.sh` |
| `ydbctl vista journal [enable\|disable\|rotate]` | `GTM/bin/{enable,disable,rotate}Journal.sh` |
| `ydbctl vista ports` | check 9430 / 8001 / 9100-9101 reachability |

These show up only when the active profile's `vista=true`. For
non-VistA YottaDB images, the subcommand tree is hidden.

### 4.13 Replication (Phase 5, out of scope initially)

`ydbctl repl source start/stop/status/showbacklog`,
`ydbctl repl receiver start/stop/status`,
`ydbctl repl instance create/edit`,
`ydbctl repl rollback --fetchresync`.

### 4.14 Convenience

| Subcommand | Wraps |
|---|---|
| `ydbctl gde [SCRIPT]` | run GDE on stdin or `@SCRIPT` |
| `ydbctl docs <topic>` | open `https://docs.yottadb.com/...` matching topic |
| `ydbctl which <op>` | print the *underlying* command for an op (debug aid) |

---

## 5. Output contract

Identical envelope to `irisctl` for cross-tool consistency.

### 5.1 Success

```json
{
  "v": 1,
  "ok": true,
  "command": "regions",
  "data": [
    {"name": "DEFAULT", "file": "/data/yottadb.dat", "journal": "on",
     "block_size_bytes": 4096, "transaction_number": 12387},
    {"name": "VISTA", "file": "/data/vista.dat", "journal": "on",
     "block_size_bytes": 4096, "transaction_number": 1845902}
  ],
  "warnings": []
}
```

### 5.2 Error

```json
{
  "v": 1,
  "ok": false,
  "command": "exec",
  "error": {
    "code": "ipc_orphans",
    "message": "Orphan IPC keys detected; previous container shutdown was unclean",
    "hint": "ydbctl rundown",
    "ref": "ydb-cli-surface.md#13-gotchas"
  }
}
```

### 5.3 Stable error codes

| Code | Meaning | Exit |
|---|---|---|
| `ok` | success | 0 |
| `usage` | invalid arguments | 2 |
| `instance_not_running` | container is stopped/missing | 3 |
| `ipc_orphans` | rundown needed before mutation | 4 |
| `gtmsecshr_down` | helper not reachable on `$ydb_tmp` socket | 4 |
| `auth_required` | optional service (GUI/ROcto) returned 401 | 5 |
| `not_found` | region / global / routine / file missing | 6 |
| `ydb_error` | underlying YottaDB error (with $ZSTATUS captured) | 7 |
| `docker_error` | container-level failure | 8 |
| `network_error` | port unreachable / HTTP failed | 9 |
| `internal` | wrapper bug | 1 |

The IRIS-only `license_exhausted` code does not exist for YottaDB.

### 5.4 Warnings field

Non-fatal observations attach to `data.warnings[]` rather than
elevating to an error. Examples:

- `"orphan_ipc_keys": 3` after a successful read — operation worked
  but the user should run `rundown`.
- `"gld_not_found_at_ydb_gbldir"` — environment looks unusual.
- `"journal_file_lost"` — region with `*.mjl_lost` flag.

---

## 6. Configuration

### 6.1 Config file

`~/.config/ydbctl/config.toml`:

```toml
default_profile = "vista-ydb"

[profiles.vista-ydb]
container = "vista-ydb"
host = "127.0.0.1"
data_dir = "~/data/vista-ydb"
ydb_dist = "/usr/local/lib/yottadb/r202"
ydb_gbldir = "/data/yottadb.gld"
vista = true                                    # unlocks ydbctl vista *

[profiles.vista-ydb.services]
rocto_port = 1337
gui_port = 9080
gtcm_port = 6789

[profiles.plain]
container = "ydb"
data_dir = "~/data/ydb"
ydb_dist = "/usr/local/lib/yottadb/r202"
ydb_gbldir = "/data/yottadb.gld"
vista = false
```

### 6.2 Env var overrides

`YDBCTL_PROFILE`, `YDBCTL_CONTAINER`, `YDBCTL_GBLDIR`,
`YDBCTL_OUTPUT=json|human`, `YDBCTL_NO_IPC_CHECK`.

### 6.3 No creds in config file

YottaDB core has no auth. For optional services that need creds
(ROcto, GUI), reference env vars by name (`auth_pw_env =
"YDBCTL_VISTA_GUI_PW"`) — never store in TOML.

---

## 7. Implementation strategy

### 7.1 Language: Python (with `uv`)

Same rationale as `irisctl`:
- Surface is ~30 subcommands × multiple modes.
- Rafael's default toolchain is Python (`uv` / `ruff` / `mypy` /
  `pytest` per `~/.claude/CLAUDE.md`).
- Easy to package as a single-file zipapp or via PyInstaller.

For YottaDB specifically:
- The `mupip dumpfhead`, `mupip integ`, `gde show`, `lke show` outputs
  are line-based text — Python's regex/dataclass parsing is far
  cleaner than awk pipelines.
- The `mupip` binaries return non-zero on warnings (e.g. integ
  finds a fixable issue) but the line-level output is what matters —
  Python lets us classify cleanly.
- A future `ydblib` Python module could share parsers with `irisctl`
  for the small overlap (status / ports / docker inspect).

### 7.2 Project layout

```
~/projects/ydbctl/
├── pyproject.toml          # uv-managed
├── Makefile                # .venv/bin/ prefixes (per CLAUDE.md hard rule)
├── README.md
├── src/ydbctl/
│   ├── __init__.py
│   ├── cli.py              # argparse tree + dispatch
│   ├── config.py           # profiles, env, defaults
│   ├── output.py           # JSON envelope, human renderer
│   ├── docker_api.py       # docker inspect / start / stop / cp wrappers
│   ├── exec_session.py     # yottadb -direct heredoc with HALT injection
│   ├── ipc.py              # IPC orphan detection (ipcs + mupip ftok)
│   ├── parsers/
│   │   ├── dumpfhead.py    # mupip dumpfhead output → JSON
│   │   ├── gde_show.py     # gde show output → JSON (regions/segments/names)
│   │   ├── integ.py        # mupip integ output → JSON
│   │   ├── lke_show.py     # lke show output → JSON
│   │   └── journal_show.py # mupip journal -show → JSON
│   ├── services/           # gui, rocto, web, gtcm
│   └── commands/
│       ├── status.py
│       ├── regions.py
│       ├── dbinfo.py
│       ├── journal.py
│       ├── backup.py
│       ├── integ.py
│       ├── locks.py
│       ├── exec_cmd.py
│       ├── sql.py
│       ├── lifecycle.py
│       ├── rundown.py
│       └── vista.py
└── tests/
    ├── conftest.py         # spins up a clean ydb container per session
    ├── parsers/
    │   ├── fixtures/       # captured real outputs from mupip/gde/lke
    │   └── test_*.py       # parser unit tests against fixtures
    ├── test_status.py
    ├── test_regions.py
    └── …
```

### 7.3 Dependencies

| Tool | Why |
|---|---|
| Python 3.11+ | tomllib, modern typing |
| `httpx` | for service-mode HTTP calls (GUI, Web) |
| `psycopg` (binary) | `ydbctl sql` against ROcto |
| `click` (or argparse) | CLI tree |
| `rich` (optional) | only if `--human` mode needs tables |
| `pytest` | testing |
| `ruff`, `mypy` | per CLAUDE.md |

Runtime: `docker` CLI on PATH; container running for ops that need
it.

### 7.4 IPC pre-check pattern

Lightweight check before any mutating subcommand:

```python
def precheck_ipc(profile) -> list[str]:
    """Return list of warnings (empty = clean)."""
    out = docker_exec(profile, ["mupip", "ftok", "-nohead", "-only",
                                "/data/yottadb.dat"])
    cur = parse_ipc_keys(out)
    leftover = ipcs_keys_for_user(profile) - cur
    return [f"orphan_ipc_keys:{len(leftover)}"] if leftover else []
```

A separate background fact: `gtmsecshr` self-shuts-down after 60min
idle, so a single-key-leftover may not indicate a problem. The
wrapper distinguishes "leftover from this generation of containers"
(real warning) vs "leftover semaphore that gtmsecshr will reap"
(cosmetic).

### 7.5 Heredoc safety for `yottadb -direct`

The `exec_session` module is the one place that touches
`yottadb -direct`. Two guarantees:

1. **Always append `HALT`.** If user-supplied script ends with
   `QUIT`/`Q`, replace with `HALT`.
2. **Always use `<<'YDBCTL_EOF'`** (single-quoted heredoc tag) so
   shell `$VARS` aren't expanded into the M code.

```python
def session_exec(profile, region: str | None, script: str) -> str:
    if region:
        script = f'ZN "{region}"\n' + script
    if not _ends_with_halt(script):
        script += "\nHALT\n"
    return subprocess.check_output(
        ["docker", "exec", "-i", profile.container,
         "yottadb", "-direct"],
        input=script,
        text=True,
        timeout=profile.exec_timeout,
    )
```

### 7.6 Output parsers

Each `mupip`/`gde`/`lke` subcommand has a fixed-format text
output. Parsers go in `src/ydbctl/parsers/` with snapshot-based
unit tests. Fixtures captured from a live container:

- `mupip dumpfhead` — 50+ named fields per region
- `gde show -region` — table form
- `lke show -all` — list of `lock^subscript pid` lines
- `mupip integ -fast` — region summary lines + error/warning lines
- `mupip journal -show` — journal-state record list

Snapshot tests pin the output → JSON shape, so future YottaDB
version bumps can be detected instantly.

---

## 8. Phasing

Each phase ships independently.

### Phase 1 — Read-only floor (no mutation, no service deps)

**Subcommands:** `status`, `version`, `ports`, `logs`, `env`,
`health`, `regions`, `segments`, `globals`, `files`, `dbinfo`,
`ipc`, `journal status`, `journal verify`.

**Key infrastructure:** docker-exec wrappers, output envelope, IPC
scanner, parsers for `dumpfhead` / `gde show` / `journal show`.

**LOC estimate:** ~600.

**Tests:** parser unit tests against captured fixtures + integration
tests against a clean ydb container.

**Ship criterion:** AI agent can answer "what regions exist", "is
the DB healthy", "is journaling on", "are there orphan IPC keys"
with one command each.

### Phase 2 — Execute (M / SQL)

**Subcommands:** `exec`, `sql` (Octo subprocess; ROcto if running),
`shell`, `globals show/export`, `routines list/get/put/compile`.

**LOC estimate:** +250.

**Tests:** round-trip ObjectScript / M routine; SQL via Octo
subprocess; verify HALT injection for hung-session avoidance.

**Ship criterion:** AI agent can run M code and SQL without writing
heredocs.

### Phase 3 — Maintenance & recovery

**Subcommands:** `backup`, `restore`, `extract`, `load`, `integ`,
`reorg`, `freeze`, `extend`, `locks show/clear/cleanup`, `rundown`,
`recover`.

**LOC estimate:** +300.

**Tests:** backup → restore round-trip; integ on a clean DB; rundown
after simulated `docker kill`.

**Ship criterion:** Whole disaster-recovery cycle scriptable.

### Phase 4 — Service management & VistA layer

**Subcommands:** `gui start/stop/status`, `rocto start/stop/status`,
`web start/stop/status`, `gtcm start/stop`, `journal enable/disable/
rotate`, `vista rpcbroker/vistalink/hl7/journal/ports` (when
profile has `vista=true`).

**LOC estimate:** +250.

**Tests:** start each service in a docker-vista-fork ydb container;
verify port reachability; clean shutdown.

**Ship criterion:** All optional listeners manageable from one CLI;
VistA layer auto-detected.

### Phase 5 — Replication, polish, distribution

Replication subcommands. Profiles, shell completion, `--watch`
modes, `which` debug command, JSON-RPC mode (single persistent
process for AI agents instead of spawning many CLI calls),
pip-installable distribution.

**LOC estimate:** +300.

---

## 9. Testing strategy

1. **Pytest harness with session-scoped fixture** that ensures a
   clean ydb container is up; `ydbctl status` is the readiness probe.
2. **Real container only.** No mocking the YottaDB process per
   `~/.claude/CLAUDE.md` "No mocks unless unavoidable."
3. **Fixture-driven parser tests.** Each parser has a `fixtures/`
   directory with real captured outputs from `mupip` / `gde` / `lke`.
   Parser unit tests run independently of any container.
4. **Snapshot tests for JSON envelopes.** Hand-curated examples for
   each major subcommand; future YottaDB-version drift detected
   immediately.
5. **Crash-recovery tests.** Simulate `docker kill`, verify
   `ydbctl status` reports `ipc_orphans`, `ydbctl rundown` clears
   them, next operation succeeds.
6. **Integration tests double as documentation.**

---

## 10. Risks & open questions

1. **Output parser brittleness.** `mupip` output formats are stable
   but not contractual. New YottaDB versions could shift columns.
   Mitigation: snapshot tests + version-aware parsers (`r2.02` vs
   `r2.04` paths), with a fallback to "raw" mode that returns the
   subprocess stdout unstructured if parsing fails.

2. **Multi-region complexity.** YottaDB DBs can have dozens of
   regions across multiple `.gld` files. Subcommands need to handle
   `--region '*'`, `--region NAME`, `--gld /path/to.gld` with
   sensible defaults. Phase 1 assumes a single `.gld`.

3. **`gtmsecshr` lifecycle bookkeeping.** The 60-min idle shutdown
   of `gtmsecshr` is benign but `ydbctl status` should distinguish
   "gtmsecshr not running because idle" vs "gtmsecshr not running
   because crashed". Probe: tickle it with a no-op `mupip ftok` —
   if it auto-spawns, it was idle; if it fails, something's broken.

4. **VistA layer cohabitation.** The `ydbctl vista *` subcommands
   only make sense for the docker-vista-fork's YottaDB build. Two
   options:
   - **(a) Conditional on profile.** `vista=true` in the TOML
     unlocks the subtree. Simple but couples YottaDB and VistA
     concerns.
   - **(b) Separate `vistactl` tool.** Cleaner separation but
     duplicates docker-exec / config plumbing.
   - **Proposal: (a) for v1.** If it grows, factor out.

5. **VistA layer also has IRIS variant.** The same VistA install
   exists on IRIS. Should `vistactl` (if extracted) wrap both
   `irisctl` and `ydbctl` underneath? Worth considering but not
   blocking.

6. **Container running as root.** YottaDB requires it
   (gtmsecshr setuid). Hardened k8s `runAsNonRoot` breaks YDB.
   Wrapper should detect and issue a warning rather than failing
   silently.

7. **No HTTP fallback for metrics.** Unlike IRIS, there's no free
   metrics endpoint. Every "give me current state" call goes
   through `mupip dumpfhead` or `$VIEW()`, which is more expensive
   than `/api/monitor/metrics`. Mitigation: cache `dumpfhead` output
   for ~5s within a single `ydbctl` invocation.

8. **Naming.** `ydbctl` reads naturally and matches `irisctl` /
   `kubectl` / `systemctl`. Alternatives considered: `yctl` (too
   short), `ydb` (collides with the YDB shell wrapper binary in
   `$ydb_dist`), `ymctl` (ambiguous). **Pick: `ydbctl`.**

   Crucially, this does NOT conflict with Rafael's `m` toolchain
   (M-language formatter/linter/tester at `~/projects/m-cli/`)
   or the `y*` tools in his `~/projects/ydb/` learning project
   (`yrun`, `yutil`, `ynew`, etc. — these are TDD workflow tools
   for routines, not DB management).

9. **Distribution.** `~/scripts/bin/ydbctl` symlink to the project
   entrypoint for personal use; eventually `pipx install ydbctl`
   from a private index for portability.

---

## 11. What this displaces

| Replaced | Replacement |
|---|---|
| Hand-typed `docker exec -i NAME yottadb -direct …` | `ydbctl exec` |
| `docker exec NAME mupip dumpfhead -file …` per region | `ydbctl dbinfo` |
| `docker exec NAME mupip integ -fast` | `ydbctl integ` |
| `docker exec NAME mupip backup -bytestream …` | `ydbctl backup` |
| `docker exec NAME mupip rundown -region "*"` | `ydbctl rundown` |
| `docker exec NAME lke show -all` | `ydbctl locks show` |
| `docker exec NAME gde <<'END' SHOW END` | `ydbctl regions` |
| `GTM/bin/{rpcbroker,vistalink,hl7,enableJournal,...}.sh` | `ydbctl vista *` |
| Restoring after `docker kill` | `ydbctl recover && ydbctl rundown && ydbctl start` |

The repo's `GTM/bin/*.sh` keep their place as the ground-truth
reference; `ydbctl` parses them but doesn't replace them outright.

---

## 12. Out of scope

- A long-running daemon. Stateless commands compose better.
- A web UI. The YDB GUI on 9080 already exists and `ydbctl gui start`
  manages it.
- Wrapping every `mupip` flag exhaustively. Only the surfaces an AI
  agent or operator reaches for in normal work — the
  `ydbctl which` escape hatch documents the underlying command for
  the rest, and `ydbctl gde` / `ydbctl exec` are the safety valves.
- Cross-platform (Windows). Linux-only. The surface doc notes
  Windows differences for context but the wrapper targets the host
  OS that runs the docker-vista YottaDB container.
- Replacing `mupip` / `lke` / `gde` / `dse` themselves. They are
  stable and authoritative; the wrapper sits above them.
- Source-level M tooling (formatter, linter, tester). Rafael's
  `m` toolchain at `~/projects/m-cli/` already covers that.
  `ydbctl` is for DB management, not language tooling — the two
  are explicitly complementary.

---

## 13. Bootstrapping next steps

If this proposal is accepted:

1. Create `~/projects/ydbctl/` from `~/claude/templates/python/`.
2. Capture parser fixtures: run `mupip dumpfhead`, `gde show -all`,
   `lke show -all`, `mupip integ -fast`, `mupip journal -show`
   against the docker-vista YottaDB container (when available) and
   save outputs to `tests/parsers/fixtures/`.
3. Implement Phase 1 (~600 LOC, ~1-2 sessions). Read-only floor
   gives an AI agent a complete picture of any YottaDB instance
   without ever mutating state.
4. Symlink `~/scripts/bin/ydbctl` → project entrypoint.
5. Iterate Phases 2–5 as needed; each ships independently.

The parser-driven design means most of the complexity is in
deterministic, snapshot-tested transforms — not in IRIS-style
network plumbing. A complete first version (Phases 1–3) is realistic
in a single afternoon's work, similar to `irisctl`.

---

## 14. Cross-tool consistency with `irisctl`

Where IRIS and YottaDB serve analogous concepts, the subcommand
names and flags are identical between `irisctl` and `ydbctl`.

| Concept | `irisctl` | `ydbctl` |
|---|---|---|
| One-shot health check | `irisctl status` | `ydbctl status` |
| Container lifecycle | `irisctl start/stop/restart` | `ydbctl start/stop/restart` |
| Tail container log | `irisctl logs --tail N` | `ydbctl logs --tail N` |
| Open interactive shell | `irisctl shell --ns NS` | `ydbctl shell --region R` |
| Run M / ObjectScript | `irisctl exec --ns NS '…'` | `ydbctl exec --region R '…'` |
| Run SQL | `irisctl sql --ns NS '…'` | `ydbctl sql '…'` |
| Backup | `irisctl backup --to PATH` | `ydbctl backup --to PATH` |
| Restore | `irisctl restore --from PATH` | `ydbctl restore --from PATH` |
| Print underlying command | `irisctl which <op>` | `ydbctl which <op>` |
| Output | JSON envelope, `v: 1` | JSON envelope, `v: 1` |
| Error code shape | `{code, message, hint, ref}` | same |

Code-sharing path: factor common pieces (envelope, docker wrapper,
config TOML, port-probe helper) into a private `vistactl-core`
package consumed by both, OR hand-replicate to keep them
independent. **Proposal: hand-replicate for the first ship; refactor
later only if the duplication exceeds 200 LOC.**

The two tools are designed so an AI agent can drive *either*
backend — IRIS or YottaDB — without learning a different command
vocabulary. That symmetry is the load-bearing design choice.
