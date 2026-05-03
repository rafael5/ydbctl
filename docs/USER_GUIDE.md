# ydbctl User's Guide

A programmer- and AI-friendly CLI wrapper for YottaDB Docker
containers. One consistent JSON-first surface that hides the patchwork
of `docker exec`, `mupip` / `lke` / `gde` invocations, IPC bookkeeping,
and direct-mode heredocs that you'd otherwise re-type for every task.

This guide is the canonical reference: what the tool does, how it's
designed, how to install and configure it, every command, common
workflows, and the lessons we learned wiring it up against a live
container.

> **Companion documents.** This guide draws on three deeper references
> already in this repo, all worth reading on their own:
>
> - [docs/ydb-cli-surface.md](ydb-cli-surface.md) — what's actually
>   underneath the wrapper: every YottaDB binary, every mupip
>   subcommand, every env var, every gotcha.
> - [docs/ydb-cli-plan.md](ydb-cli-plan.md) — the original 5-phase
>   proposal and design contract. Read this if you want the *why*
>   for a particular decision.
> - [docs/mctl-composite.md](mctl-composite.md) — irisctl ↔ ydbctl
>   side-by-side, classifying every operation as MUMPS-portable,
>   IRIS-only, or YottaDB-only.

---

## Contents

1. [What ydbctl is, and what it isn't](#1-what-ydbctl-is-and-what-it-isnt)
2. [Background](#2-background)
   - [Design philosophy](#21-design-philosophy)
   - [The CLI surface being wrapped](#22-the-cli-surface-being-wrapped)
   - [Implementation plan: 5 phases](#23-implementation-plan-5-phases)
3. [Installation and setup](#3-installation-and-setup)
4. [Configuration](#4-configuration)
5. [Quick start](#5-quick-start)
6. [Command reference](#6-command-reference)
   - [Phase 1: inspection](#61-phase-1--read-only-inspection)
   - [Phase 2: execution](#62-phase-2--m-execution--sql--shell--globals)
   - [Phase 3: maintenance](#63-phase-3--maintenance)
   - [Phase 4: VistA layer](#64-phase-4--vista-on-yottadb-layer)
   - [Phase 5: replication + RPC](#65-phase-5--replication--json-rpc)
7. [Output contract](#7-output-contract)
8. [Common workflows](#8-common-workflows)
9. [Troubleshooting](#9-troubleshooting)
10. [Architectural lessons](#10-architectural-lessons-captured-during-the-build)
11. [Sibling project: irisctl](#11-sibling-project-irisctl)
12. [What's next](#12-whats-next)
13. [Further reading](#13-further-reading)

---

## 1. What ydbctl is, and what it isn't

**It is** a single command — `ydbctl` — that drives a Dockerized
YottaDB instance through ~32 subcommands grouped into five phases.
Every command emits a versioned JSON envelope by default (or a
human-readable table with `--human`). Every command is tested
end-to-end against a real YottaDB container.

```bash
$ ydbctl status --human
container    {'status': 'running', 'running': True, ...}
ydb_release  r2.07
listeners    [{'role': 'ydb_gui', 'host_port': 9080, 'reachable': True}, ...]
ipc          {'shared_memory': [], 'semaphores': [], 'shm_count': 0, 'sem_count': 0}

$ ydbctl exec 'W $ZV,!' --human
mode    xcmd
output  GT.M V7.1-002 Linux x86_64

$ ydbctl backup --to ~/data/backups/ydb --human
region          DEFAULT
host_path       /home/rafael/data/backups/ydb/default.bk
size_bytes      4331520
online          yes
container_path  /tmp/ydbctl-backup-default.bk
```

**It isn't** a replacement for `mupip`, `lke`, `gde`, or `dse`. Those
tools remain canonical and authoritative; ydbctl just makes them
easier to drive from a script or an AI agent. The
`ydbctl which <op>` subcommand prints the underlying invocation for
any operation, exactly so you can drop down to the raw tool when
you need to.

**It also isn't** a YottaDB language tool. M-language tooling
(formatter, linter, test runner) lives in Rafael's separate `m`
toolchain at `~/projects/m-cli/`. ydbctl is for *managing the
container* and the database it holds, not the M code itself.

---

## 2. Background

### 2.1 Design philosophy

The five principles, in order of importance:

1. **JSON-first.** Default output is a versioned envelope
   (`{"v": 1, "ok": true, "command": ..., "data": ..., "warnings": []}`).
   `--human` swaps to a table for terminal use; `--pretty` indents
   the JSON. The shape never changes between commands. AI agents
   can rely on it.

2. **Real-container testing only.** Per
   [the project plan §9](ydb-cli-plan.md#9-testing-strategy) and
   the global `~/.claude/CLAUDE.md` "no mocks unless unavoidable"
   rule, every integration test runs against an actual `ydb-test`
   YottaDB container. There is no mocked YottaDB anywhere in the
   codebase. The cost is some test slowness (~9.5s for 135 tests);
   the payoff is that bugs surface against the real binaries, not
   against hypothetical stubs.

3. **Symmetric with `irisctl`.** The sibling tool for IRIS Community
   Edition uses the *same* envelope shape, *same* error codes, and
   identical subcommand names where the concept maps cleanly
   (`status`, `version`, `ports`, `logs`, `exec`, `sql`, `shell`,
   `backup`, `restore`, `which`, `rpc`). An AI agent that learns
   one tool gets most of the other for free. See
   [docs/mctl-composite.md](mctl-composite.md) for the
   88-operation side-by-side comparison.

4. **Subprocess-orchestration over network protocols.** Unlike
   IRIS, vanilla YottaDB has no built-in HTTP/REST surface — every
   operation goes through a subprocess (`mupip`, `lke`, `gde`,
   `yottadb`). The wrapper accepts that and centralizes the
   plumbing in [src/ydbctl/ydb_exec.py](../src/ydbctl/ydb_exec.py),
   so command modules deal with parsed envelopes, never raw process
   I/O.

5. **Idempotency where possible.** `start` is a no-op when already
   running. `rundown` is safe even with no orphans. Watch-mode polls
   never mutate. Mutating ops (`backup`, `freeze`, `restore`,
   `rollback`) make their effect predictable and reversible.

### 2.2 The CLI surface being wrapped

YottaDB ships as a **library**, not a daemon. Every M process opens
`.dat` files directly via `mmap` + System V IPC. There is no
listener to "start the database" — the database "exists" the moment
a `.dat` exists. This shapes everything:

- Each ydbctl subprocess sources `$ydb_dist/ydb_env_set` first
  ([src/ydbctl/ydb_exec.py](../src/ydbctl/ydb_exec.py:23)) so
  `ydb_dist`, `ydb_routines`, `ydb_gbldir` etc. are populated
  consistently.
- `ipc` exposes `ipcs -m` / `ipcs -s` directly, because there's no
  daemon abstracting shared memory.
- After any unclean shutdown, `mupip rundown` is mandatory before
  next use. ydbctl exposes this as `ydbctl rundown`.
- There are no LU (license unit) costs to pay — YottaDB is Apache
  2.0. Where irisctl has a `license_exhausted` error code at exit
  4, ydbctl has `ipc_orphans` instead.

The full underlying surface — every binary, every flag, every gotcha
— lives in [docs/ydb-cli-surface.md](ydb-cli-surface.md). High
points:

| Tool | Purpose |
|---|---|
| `yottadb` / `mumps` | M language runtime; direct-mode REPL; `-run <entryref>` |
| `mupip` | Multi-purpose admin: backup, restore, integ, reorg, journal, replicate, rundown … |
| `gde` | Global Directory Editor — only safe way to mutate `.gld` |
| `lke` | M Lock Editor — view/clear active LOCKs |
| `dse` | Database Structure Editor — block-level surgery (expert-only) |
| `gtmsecshr` | setuid-root helper daemon — auto-spawned, never invoked directly |

ydbctl wraps the first four (and `gtmsecshr` is invisible — it just
works). `dse` is intentionally not wrapped: anything that can corrupt
a database in one keystroke shouldn't be hidden behind a JSON
envelope.

### 2.3 Implementation plan: 5 phases

The build follows the phasing locked in
[docs/ydb-cli-plan.md](ydb-cli-plan.md):

| Phase | Theme | Subcommands |
|---|---|---|
| 1 | Read-only floor (no mutation) | `status`, `version`, `ports`, `env`, `regions`, `files`, `dbinfo`, `ipc`, `logs`, `health`, `which` |
| 2 | M execution + globals | `exec`, `sql`, `shell`, `globals show/export` |
| 3 | Maintenance | `integ`, `reorg`, `freeze`, `locks show/clear`, `rundown`, `recover`, `backup`, `restore` |
| 4 | VistA layer | `vista rpcbroker/vistalink/hl7/journal/ports` (services skipped per request) |
| 5 | Replication + AI integration | `repl source/receiver/instance/rollback`, `rpc` (JSON-RPC 2.0) |

Each phase shipped in its own commit, independently testable. The
commit log is the canonical timeline:

```
1dad9ff README: sync Roadmap to shipped state for Phases 3–5
c68b337 Phases 4 + 5: VistA layer + replication + JSON-RPC
0189688 Phase 2: exec, sql, shell, globals
e12da8d Phase 3: maintenance ops
de0ac6a README: Phase 3 maintenance commands
8906ec4 Initial Phase 1: ydbctl read-only floor
```

Phase 4's "services" subset (GUI, ROcto, Web, GT.CM) and Phase 5's
pipx packaging were both deliberately skipped — see the project
[memory entry](https://github.com/rafael5/claude/blob/main/memory/project_ydbctl.md)
for context.

---

## 3. Installation and setup

Three things have to be in place: a Docker daemon, a YottaDB
container, and the `ydbctl` Python project.

### 3.1 Prerequisites

| Item | Why |
|---|---|
| Docker | Every command shells into a container via `docker exec` |
| Python ≥ 3.12 | uv-managed venv; modern typing |
| `uv` | Project package manager (per `~/.claude/CLAUDE.md`) |
| ~6 GB free disk | YottaDB image + DAT files + occasional backups |

### 3.2 Bring up a YottaDB test container

The default profile expects a container named `ydb-test` with
`~/data/ydb-test/` bind-mounted to `/data`:

```bash
mkdir -p ~/data/ydb-test
docker run --name ydb-test -d \
  -v ~/data/ydb-test:/data \
  -p 9080:9080 -p 9081:9081 \
  yottadb/yottadb-base:latest-master \
  bash -c 'source /opt/yottadb/current/ydb_env_set && tail -f /dev/null'
```

After first launch, `~/data/ydb-test/r2.07_x86_64/g/` holds:
- `yottadb.dat` / `yottadb.gld` (default region)
- `%ydbocto.dat`, `%ydbaim.dat` (plugin databases)

The `tail -f /dev/null` is the simplest way to keep the container
alive — `yottadb-base` has no default `ENTRYPOINT`/`CMD` and would
exit immediately otherwise.

> **Why this image, and what's missing.** `yottadb/yottadb-base` is
> the minimal upstream image. It does **not** include Octo (the SQL
> engine) or the GUI plugin. `ydbctl sql` will return a clean
> `not_found` error in this image — switch to
> `yottadb/yottadb-debian` or run `ydbinstall --octo` inside the
> container to add it.

### 3.3 Set up the project

```bash
git clone https://github.com/rafael5/ydbctl.git
cd ydbctl
make install         # uv sync + pre-commit hooks
make test            # 135 tests, ~9.5s — confirms container is reachable
```

To use the `ydbctl` command directly anywhere, symlink the venv
entrypoint onto your `PATH`:

```bash
ln -s ~/projects/ydbctl/.venv/bin/ydbctl ~/scripts/bin/ydbctl
```

(Or invoke as `python -m ydbctl ...` — both work.)

### 3.4 Optional: shell completion

argcomplete is wired into the CLI parser. Activate by adding to
your shell rc:

```bash
# bash / zsh
eval "$(register-python-argcomplete ydbctl)"
```

After that, `ydbctl <Tab>` completes subcommands and flags.

---

## 4. Configuration

### 4.1 Resolution order

Profile values resolve in this order (lowest to highest precedence):

1. Built-in defaults (`ydb-test` container, `~/data/ydb-test`,
   `/opt/yottadb/current` for `ydb_dist`).
2. `~/.config/ydbctl/config.toml`, the `[profiles.<name>]` table for
   the active profile.
3. `YDBCTL_*` environment variables.
4. CLI flags (only `--profile NAME` selects which profile is active).

### 4.2 The TOML config file

```toml
default_profile = "ydb-test"

[profiles.ydb-test]
container       = "ydb-test"
host            = "127.0.0.1"
data_dir        = "~/data/ydb-test"
ydb_dist        = "/opt/yottadb/current"
gui_port        = 9080
gui_stats_port  = 9081
rocto_port      = 1337
gtcm_port       = 6789

# A second profile for a docker-vista-fork YottaDB build:
[profiles.foia-ydb]
container          = "foia"
host               = "127.0.0.1"
data_dir           = "~/data/foia-ydb"
ydb_dist           = "/opt/yottadb/current"
vista              = true
vista_instance     = "foia"
vista_rpc_port     = 9430
vista_vistalink_port = 8001
vista_hl7_port     = 5001
```

Switch with `ydbctl --profile foia-ydb status` or
`YDBCTL_PROFILE=foia-ydb ydbctl status`.

### 4.3 Environment variables

| Variable | Effect |
|---|---|
| `YDBCTL_PROFILE` | Select a profile |
| `YDBCTL_CONTAINER` | Override container name |
| `YDBCTL_HOST` | Override host (default `127.0.0.1`) |
| `YDBCTL_DATA_DIR` | Override the host data directory |
| `YDBCTL_YDB_DIST` | Override `$ydb_dist` inside the container |

### 4.4 The VistA-layer flag

`profile.vista = true` (default `false`) is the gate for the
[Phase 4 VistA subcommands](#64-phase-4--vista-on-yottadb-layer).
Without it, every `ydbctl vista *` call returns a `usage` error
explaining that VistA-layer ops are disabled. This guard prevents
accidentally running RPC Broker / VistALink / HL7 helpers against a
non-VistA YottaDB image (where the helper scripts don't exist).

---

## 5. Quick start

The five commands you'll run most:

```bash
# Is everything OK?
ydbctl status --human

# What version of YottaDB is in the container?
ydbctl version --human

# What regions are defined? Where do their DATs live?
ydbctl regions --human
ydbctl files --human
ydbctl dbinfo --human

# Run a one-line M command:
ydbctl exec 'W $H,!'

# Take a backup of the default region:
ydbctl backup --to ~/data/backups/today --human
```

If `status` shows `running: True` and `health: green`, you're set.

---

## 6. Command reference

This section is comprehensive — every subcommand, every flag,
every error path. Skip ahead to whichever phase you need.

### 6.1 Global flags

These work *before or after* the subcommand:

| Flag | Effect |
|---|---|
| `--profile NAME` | Select a profile (default from `default_profile`) |
| `--json` | JSON output (default) |
| `--human` | Render envelope as a human-readable table |
| `--pretty` | Indent JSON output |

### 6.2 Phase 1 — read-only inspection

No mutation, no IPC consumed. Safe to run as often as you like.

| Command | Purpose |
|---|---|
| `ydbctl status` | Composite container + version + IPC + listeners snapshot |
| `ydbctl version` | YottaDB engine version + Docker image labels |
| `ydbctl ports` | Reachability table for optional service ports (9080/9081/1337/6789) |
| `ydbctl env [NAME]` | Show `ydb_*` / `gtm*` env vars from inside the container |
| `ydbctl regions` | List regions via `gde show` (raw + parsed) |
| `ydbctl files` | Enumerate `.gld` / `.dat` / `.mjl` / `.repl` files under `$ydb_dir` |
| `ydbctl dbinfo [REGION] [--full]` | `mupip dumpfhead` summary for a region or `--file PATH` |
| `ydbctl ipc` | Shared memory + semaphore inventory; flags orphans |
| `ydbctl logs [--tail N]` | Tail recent journal records |
| `ydbctl health` | Composite green/yellow verdict with check breakdown |
| `ydbctl which [OP]` | Explain the underlying mechanism for any op (debug aid) |

Examples worth trying:

```bash
# What's actually under the hood for `ydbctl backup`?
$ ydbctl which backup --human

# Inspect just the DAT-header summary, not the full record dump:
$ ydbctl dbinfo --human

# Full dump if you want every sgmnt_data field:
$ ydbctl dbinfo --full | jq '.data.full | keys' | head -20

# All env vars matching a prefix:
$ ydbctl env | jq '.data.vars | with_entries(select(.key | startswith("ydb_repl")))'
```

### 6.2 Phase 2 — M execution / SQL / shell / globals

Runs M code or SQL inside the container. No license costs, but
each invocation spawns a process.

| Command | Purpose |
|---|---|
| `ydbctl exec '<m-code>'` | Run M via `yottadb -run %XCMD` (default — fastest, cleanest output) |
| `ydbctl exec --stdin` | Read M from stdin |
| `ydbctl exec --file PATH` | Read M from a host-side file |
| `ydbctl exec --run "ENTRY^ROUTINE" [--arg X]` | Invoke a labelled entry via `yottadb -run` |
| `ydbctl exec --direct '<m>'` | Multi-line via `yottadb -direct` heredoc + HALT injection |
| `ydbctl sql '<sql>' [--file PATH]` | SQL via Octo (returns `not_found` if Octo missing) |
| `ydbctl shell [--dry-run]` | Interactive `yottadb -direct` proxy via `os.execvp` |
| `ydbctl globals show NAME` | Dump `^NAME` subtree (guarded `IF $D(^X) ZWRITE ^X`) |
| `ydbctl globals export NAME [--to PATH] [--format ZWR\|GO\|BINARY]` | Extract to host file |

Examples:

```bash
# Set a global, then dump it:
ydbctl exec 'S ^DEMO("X")=42 S ^DEMO("Y")="hi"'
ydbctl globals show DEMO --human

# Run a multi-line script that needs HALT injection:
ydbctl exec --direct '
S X=1
F i=1:1:5 S X=X*2
W X,!
'

# Export a global to a tarball-friendly ZWR file:
ydbctl globals export DEMO --to ~/data/exports/demo.zwr --human

# Run an entry point in an installed routine (passes args via $ZCMD):
ydbctl exec --run "MAIN^MYAPP" --arg "input.csv" --arg "output.json"
```

Default vs `--direct` mode trade-off:
- `%XCMD` is one-shot, single-line. Multiple commands separated by
  spaces work; `\n` newlines flatten to spaces. Cleanest output —
  no `YDB>` prompts.
- `--direct` accepts multi-line scripts (separate logical lines).
  HALT is auto-appended; trailing `QUIT`/`Q` is auto-replaced.
  YDB> prompts are stripped from the output.

### 6.3 Phase 3 — maintenance

The operationally interesting commands. Most are read-only or
idempotent; the destructive ones (`restore`, `rollback`) are
`--yes`-gated.

| Command | Purpose |
|---|---|
| `ydbctl integ [--region R] [--full]` | `mupip integ -fast/-full` integrity check |
| `ydbctl reorg [--region R] [--truncate]` | `mupip reorg` — defrag/coalesce |
| `ydbctl freeze --on/--off [--region R]` | `mupip freeze` — suspend/resume DB updates |
| `ydbctl locks show [--region R]` | `lke show -all` — list active M LOCKs |
| `ydbctl locks clear [--region R] --yes` | `lke clear -all` (mutating) |
| `ydbctl rundown [--region R]` | `mupip rundown` — release orphan IPC |
| `ydbctl recover [--region R] [--journal-file F] [--forward]` | `mupip journal -recover` |
| `ydbctl backup [REGION] [--to PATH] [--offline] [--dry-run]` | `mupip backup -bytestream` + `docker cp` |
| `ydbctl restore --from F --target DAT --yes [--dry-run]` | `docker cp` + `mupip restore` |

Examples:

```bash
# Daily check: integ all regions
ydbctl integ --human

# Flag-on backup before risky work, then turn freeze off:
ydbctl freeze --on --region DEFAULT
trap 'ydbctl freeze --off --region DEFAULT' EXIT
ydbctl backup --offline --to ~/data/backups/$(date +%Y%m%d)

# After a docker kill, clean orphan IPC:
ydbctl rundown --human

# Inspect what restore *would* do without actually doing it:
ydbctl restore --from ~/backup.bk --target /data/r2.07_x86_64/g/yottadb.dat --dry-run
```

> **`mupip restore` and TN-alignment.** A backup-then-restore in
> the same container session generally fails with `MUPRESTERR`
> because the backup itself advances the DB's transaction number.
> This is mupip's contract, not a wrapper bug. Restore is for
> "rebuild from a known-good backup against a fresh or rolled-back
> DB", not "undo my last operation."

### 6.4 Phase 4 — VistA-on-YottaDB layer

These are wrappers around the helper scripts that
[docker-vista-fork](https://github.com/rafael5/docker-vista-fork)
installs at `/home/<vista_instance>/bin/`. They show up only when
`profile.vista=true`; otherwise they refuse cleanly.

| Command | Purpose |
|---|---|
| `ydbctl vista rpcbroker [start\|stop\|status]` | RPC Broker listener (default port 9430) |
| `ydbctl vista vistalink [start\|stop\|status]` | VistALink listener (default port 8001) |
| `ydbctl vista hl7 [start\|stop\|status]` | VistA HL7 v2.x listener (default port 5001) |
| `ydbctl vista journal {enable\|disable\|rotate}` | Run the matching `enableJournal.sh` etc. |
| `ydbctl vista ports` | TCP-reachability table for the three VistA listeners |

The service scripts (`rpcbroker.sh`, `vistalink.sh`, `hl7.sh`) are
foreground listeners — they `exec mumps -run GTMLNX^XWBTCPM` (or
similar) and stay running. ydbctl handles that:
- `start` → `nohup bash <script>.sh > /tmp/<svc>.out 2>&1 &` + echo PID
- `stop` → `pkill -f <script>.sh`
- `status` → tcp-port reachability + `pgrep -f` inside the container

Example (against a hypothetical VistA-on-YottaDB build):

```bash
$ ydbctl --profile foia-ydb vista rpcbroker start --human
service     rpcbroker
script      rpcbroker.sh
started     yes
pid         42137
log         /tmp/rpcbroker.out

$ ydbctl --profile foia-ydb vista ports --human
listeners  [{'role': 'rpcbroker', 'host_port': 9430, 'reachable': True}, ...]
```

### 6.5 Phase 5 — replication + JSON-RPC

Replication wraps `mupip replicate`; JSON-RPC is the AI-friendly
single-process server.

#### 6.5.1 Replication

| Command | Purpose |
|---|---|
| `ydbctl repl source checkhealth` | `mupip replicate -source -checkhealth` |
| `ydbctl repl source showbacklog` | Unconsumed-records report |
| `ydbctl repl source start --port N [--secondary HOST:N] [--log F]` | Start the source server |
| `ydbctl repl source stop [--timeout-secs N]` | Graceful shutdown |
| `ydbctl repl receiver checkhealth` | `mupip replicate -receiver -checkhealth` |
| `ydbctl repl receiver start --listenport N [--log F]` | Start the receiver |
| `ydbctl repl receiver stop [--timeout-secs N]` | Graceful shutdown |
| `ydbctl repl instance create --name X (--root-primary\|--propagate-primary)` | Initialize the `.repl` instance file |
| `ydbctl repl rollback [--fetchresync N] --yes` | Roll back to a known sync point |

Status calls translate the raw `%YDB-E-REPLINSTACC` mupip error
(thrown when no `.repl` exists) into a clean `not_found` envelope:

```bash
$ ydbctl repl source checkhealth --human
ERROR (not_found): source-checkhealth: replication not configured
hint: no replication instance configured. Run `ydbctl repl instance create
       --root-primary` (or --propagate-primary) to bootstrap one.
```

#### 6.5.2 `ydbctl rpc` — JSON-RPC 2.0 single-process mode

The marquee Phase 5 feature for AI use. Reads newline-delimited
JSON-RPC 2.0 requests on stdin, writes responses on stdout. One
persistent process drives ~35 registered methods without paying
argparse + config-load startup per call.

```bash
$ printf '%s\n%s\n' \
    '{"jsonrpc":"2.0","method":"version","id":1}' \
    '{"jsonrpc":"2.0","method":"regions","id":2}' \
  | ydbctl rpc
{"jsonrpc":"2.0","id":1,"result":{"v":1,"ok":true,"command":"version",
 "data":{"ydb_release":"r2.07","upstream":"GT.M V7.1-002",...}}}
{"jsonrpc":"2.0","id":2,"result":{"v":1,"ok":true,"command":"regions",
 "data":{"regions":["DEFAULT","YDBAIM","YDBJNLF","YDBOCTO"],...}}}
```

Method names use **underscores** in place of subcommand spaces:

| CLI form | RPC method |
|---|---|
| `ydbctl globals show ^X` | `globals_show` |
| `ydbctl locks show` | `locks_show` |
| `ydbctl vista rpcbroker start` | `vista_rpcbroker` |
| `ydbctl repl source checkhealth` | `repl_source_checkhealth` |

JSON-RPC 2.0 error codes apply: `-32700` parse error, `-32600`
invalid request, `-32601` method not found, `-32602` invalid params,
`-32603` internal error. Notifications (no `id`) get no response.
The full method registry lives in [src/ydbctl/rpc.py](../src/ydbctl/rpc.py)
under `METHODS`.

---

## 7. Output contract

### 7.1 Envelope shape

Every command emits one of these:

```json
{"v": 1, "ok": true, "command": "regions", "data": {...}, "warnings": []}
{"v": 1, "ok": false, "command": "ipc",
 "error": {"code": "ipc_orphans", "message": "...", "hint": "...", "ref": "..."}}
```

Fields:

- `v`: schema version (currently 1)
- `ok`: boolean
- `command`: which subcommand emitted this
- `data` (success): a dict, list, or scalar — varies per command
- `warnings` (success, optional): list of human-readable strings
- `error` (failure): code + message + optional hint + optional doc ref

### 7.2 Error codes ↔ exit codes

Stable mapping — scripts can rely on these:

| Code | Exit | Meaning |
|---|---|---|
| `ok` | 0 | Command succeeded |
| `internal` | 1 | Unexpected wrapper bug |
| `usage` | 2 | Bad arguments / missing flag |
| `instance_not_running` | 3 | Container missing or stopped |
| `ipc_orphans` | 4 | YottaDB-specific — `mupip rundown` needed |
| `auth_required` / `auth_failed` | 5 | Missing or rejected credentials |
| `not_found` | 6 | Region / global / file / replication-instance missing |
| `ydb_error` | 7 | Underlying YottaDB error |
| `docker_error` | 8 | `docker` command failed |
| `network_error` | 9 | Port unreachable / HTTP request failed |

Note: the IRIS `irisctl` tool uses code 4 for `license_exhausted`
(IRIS Community has an LU cap; YottaDB does not). When you see code
4 from ydbctl, it always means IPC orphans — run `ydbctl rundown`.

### 7.3 Human mode

`--human` renders the envelope as a key:value block (for dict data)
or a borderless table (for list-of-dicts data). Errors render as:

```
ERROR (not_found): document USER/foo.mac not found or empty
hint: check the document name spelling
see:  docs/ydb-cli-surface.md
```

ANSI color is intentionally omitted — output stays pipe-safe.

---

## 8. Common workflows

### 8.1 Daily-driver health check

```bash
ydbctl health --human
```

If verdict is `green`, you're done. If `yellow`, the failed checks
list tells you which area to investigate (typically IPC orphans
after a `docker kill`).

### 8.2 Cold backup before risky work

```bash
backup_dir=~/data/backups/$(date +%Y%m%dT%H%M%S)
ydbctl freeze --on --region DEFAULT
trap "ydbctl freeze --off --region DEFAULT" EXIT
ydbctl backup --offline --region DEFAULT --to "$backup_dir"
echo "snapshot at $backup_dir"
```

The `trap` ensures the freeze always lifts, even if the script
crashes mid-backup.

### 8.3 Run a tutorial M routine

```bash
# Start fresh:
ydbctl exec 'K ^TUTORIAL'

# Seed the data:
ydbctl exec '
F i=1:1:10 S ^TUTORIAL("user",i,"name")="user-"_i,^TUTORIAL("user",i,"score")=i*7
'

# Inspect:
ydbctl globals show ^TUTORIAL --human

# Compute something via direct mode:
ydbctl exec --direct '
S total=0,k=""
F  S k=$O(^TUTORIAL("user",k))  Q:k=""  S total=total+^TUTORIAL("user",k,"score")
W "Total: ",total,!
'

# Cleanup:
ydbctl exec 'K ^TUTORIAL'
```

### 8.4 Recover from `docker kill`

```bash
# 1. Confirm the damage:
ydbctl ipc --human    # shows orphan shared-memory segments

# 2. Replay any pending journal records:
ydbctl recover --region '*' --human

# 3. Release IPC:
ydbctl rundown --region '*' --human

# 4. Verify integrity afterward:
ydbctl integ --human
```

### 8.5 AI-agent integration via JSON-RPC

```bash
# Start one persistent ydbctl rpc process from your agent:
exec 3>&1
coproc YDBCTL { ydbctl rpc; }

# Send requests over stdin, read responses from stdout:
echo '{"jsonrpc":"2.0","method":"status","id":1}' >&"${YDBCTL[1]}"
read -r resp <&"${YDBCTL[0]}"
echo "$resp" | jq '.result.data.container.running'
```

This avoids ~30 forks per agent turn — significant when the agent
makes many small status checks.

### 8.6 VistA listener management

(Requires `profile.vista=true` and a docker-vista-fork build.)

```bash
# Are the listeners running?
ydbctl --profile foia-ydb vista ports --human

# Bring them up:
ydbctl --profile foia-ydb vista rpcbroker start
ydbctl --profile foia-ydb vista vistalink start

# Confirm:
ydbctl --profile foia-ydb vista rpcbroker status --human

# Bring them down for maintenance:
ydbctl --profile foia-ydb vista rpcbroker stop
ydbctl --profile foia-ydb vista vistalink stop
```

---

## 9. Troubleshooting

### 9.1 "container 'ydb-test' not found"

```
{"v":1,"ok":false,"command":"status","error":{
  "code":"instance_not_running","message":"container 'ydb-test' not found"}}
```

The default profile expects a container named `ydb-test`. Either:
- Bring it up per [§3.2](#32-bring-up-a-yottadb-test-container)
- Override with `YDBCTL_CONTAINER=mycontainer ydbctl status`
- Define a profile in `~/.config/ydbctl/config.toml`

### 9.2 Octo SQL not installed

```
{"v":1,"ok":false,"command":"sql","error":{
  "code":"not_found","message":"Octo CLI not installed in this container",
  "hint":"switch to yottadb/yottadb-debian image (Octo bundled), or run
          `ydbinstall --octo` inside the container"}}
```

The base `yottadb/yottadb-base` image ships without Octo. Two fixes:

```bash
# Option A: switch images
docker run --name ydb-test -d -v ~/data/ydb-test:/data \
  yottadb/yottadb-debian:latest-master ...

# Option B: install Octo into the running container
docker exec ydb-test ydbinstall --octo
```

### 9.3 IPC orphans after `docker kill`

```
{"v":1,"ok":true,"command":"ipc","data":{"shared_memory":[...]},
 "warnings":["3 shared-memory segment(s) with nattch=0
              (may be orphan IPC — `mupip rundown -region '*'` to clean)"]}
```

Run `ydbctl rundown` to clean up. If recovery is incomplete (stale
journal too), do `ydbctl recover` first, then `rundown`.

### 9.4 `mupip restore` fails with MUPRESTERR

```
{"v":1,"ok":false,"command":"restore","error":{
  "code":"ydb_error","message":"mupip restore failed: ... MUPRESTERR ..."}}
```

This is mupip's TN-alignment contract: the DB must be at the same
transaction number where the bytestream backup begins. Backup-then-
restore in the same session generally fails because the backup
itself advances the DB's TN. Either:
- Restore against a fresh / rolled-back DB
- Use `mupip extract` + `mupip load` for logical export/import
  (different mechanism, no TN dependency)
- Use `ydbctl globals export` / loading via M routines for
  finer-grained data movement

### 9.5 `vista` commands refused

```
{"v":1,"ok":false,"command":"vista","error":{
  "code":"usage","message":"vista commands require profile.vista=true"}}
```

VistA-layer commands are gated. Set `vista = true` in your profile,
or use a profile that has it. The default `ydb-test` profile has
`vista = false` because the base YottaDB image isn't a VistA build.

### 9.6 Output looks empty after a SET

```
$ ydbctl exec 'S ^X(1)="hello"'
{"v":1,"ok":true,"command":"exec","data":{"mode":"xcmd","output":""},...}
$ ydbctl exec 'ZW ^X'
{"v":1,"ok":true,"command":"exec","data":{"mode":"xcmd","output":""},...}
```

The `ZW` (ZWRITE abbreviation) doesn't render output in YottaDB
r2.07. Use the full `ZWRITE` keyword:

```bash
ydbctl exec 'ZWRITE ^X'
# or just use the wrapper:
ydbctl globals show ^X --human
```

The `ydbctl globals show` command already does this for you.

---

## 10. Architectural lessons (captured during the build)

These came from real hours debugging against the live container.
Save someone else from re-discovering them:

### 10.1 YottaDB is a library, not a daemon

Every M process opens `.dat` files via `mmap` + System V IPC. There
is no central server to talk to. After any unclean shutdown,
`mupip rundown` is mandatory before next use. ydbctl's `ipc` /
`rundown` / `recover` commands exist precisely because there's no
daemon abstracting this.

### 10.2 `mupip` writes to stderr

Most `mupip` informational output (`BACKUPDBFILE`, `MUFILRNDWNSUC`,
`FREEZEON`, etc.) goes to stderr, not stdout. The wrapper merges
`2>&1` inside the container shell so callers see it
([src/ydbctl/ydb_exec.py](../src/ydbctl/ydb_exec.py:130)).

### 10.3 `ZW` ≠ `ZWRITE` in r2.07

The 2-letter `ZW` abbreviation produces no output in YottaDB r2.07.
The full `ZWRITE` keyword works. ydbctl's `globals show` always uses
the full keyword.

### 10.4 `mupip restore` is TN-aligned

Bytestream restores require the DB to be at the bytestream's
starting transaction number. Round-trips in the same session
generally fail. This is mupip's contract, not a wrapper bug — but
it's a real surprise for anyone expecting backup/restore to be
symmetric.

### 10.5 `mupip freeze` uses positional region

Most `mupip` subcommands take `-region <name>`; `freeze` takes the
region name as a positional argument (no `-region` flag). The
wrapper hides this asymmetry.

### 10.6 `mupip rundown` returns non-zero on missing `.repl`

In non-replicated installs, `rundown` complains that the
replication instance file isn't there (`FILENOTFND`). The actual
per-region rundowns still succeed. The wrapper detects this pattern
and returns success with a warning rather than failure.

### 10.7 `ZWRITE` raises GVUNDEF on undefined globals

Plain `ZWRITE ^DOESNOTEXIST` raises an error. The wrapper guards
with `IF $DATA(^X) ZWRITE ^X` so undefined globals return cleanly
with `count: 0`.

### 10.8 `mupip extract` / `backup` won't overwrite

If the target file exists, mupip refuses. The wrapper `rm -f`s the
in-container target before invoking — same trick used in both
`globals export` and `backup`.

### 10.9 argparse interprets `%` in help strings

A help string containing literal `%XCMD` blew up argparse's help
formatter (`%X` looks like a format specifier). Help text needs
`%%XCMD` to display correctly. The CLI uses `%%XCMD` everywhere
this matters.

---

## 11. Sibling project: irisctl

[irisctl](https://github.com/rafael5/irisctl) is the same idea for
InterSystems IRIS Community Edition Docker containers. It uses:

- The same envelope shape and error-code namespace
- Identical subcommand names where the concept maps cleanly
- The same `--profile` / `--human` / `--pretty` / `--watch` flags
- The same `rpc` JSON-RPC mode (different method registry)

Where they differ:

| Concern | ydbctl | irisctl |
|---|---|---|
| License model | None (Apache 2.0) | LU-capped (Community: 8 LU) |
| Error code 4 | `ipc_orphans` | `license_exhausted` |
| HTTP API surface | None (subprocess only) | `/api/monitor/*`, `/api/atelier/*` |
| Container default user | root (gtmsecshr setuid) | UID 51773 (irisowner) |
| Source-code CRUD | `globals export/show` (M data only) | `source list/get/put/delete/compile` (M + classes) |
| Recovery | Explicit (`rundown` / `recover`) | Implicit (daemon does it) |

Read the full 88-operation cross-classification in
[docs/mctl-composite.md](mctl-composite.md). For VistA workloads
specifically, **58% of operations are MUMPS-portable across both
backends** — the rest are admin-layer concerns invisible to VistA
itself.

---

## 12. What's next

All five phases are shipped. Possible future directions, none
currently planned:

- **Octo bootstrap helper.** A `ydbctl octo install` command that
  runs `ydbinstall --octo` inside the container and verifies SQL
  works afterward.
- **Multi-region orchestration.** Phase 1 commands take `--region`
  but assume a single `.gld`. Real-world multi-`.gld` setups would
  benefit from a `--gld PATH` flag.
- **Pipx packaging.** Skipped per the Phase 5 brief; would let
  `pipx install ydbctl` work for distribution. The
  `[project.scripts]` entry already exists, so this is small work.
- **VistA services subset of Phase 4.** GUI / ROcto / Web / GT.CM
  wrappers were deferred. They'd plug in cleanly alongside the
  existing VistA-layer commands.
- **Real `make test-slow`.** The single `@slow` test (backup →
  restore round-trip) is currently the only slow-marked test.
  Real lifecycle round-trips (full container stop/start) would be
  a useful additions.

---

## 13. Further reading

### In this repo

- [docs/ydb-cli-surface.md](ydb-cli-surface.md) — the YottaDB
  surface this wraps. 757 lines, fully cited.
- [docs/ydb-cli-plan.md](ydb-cli-plan.md) — the original 5-phase
  proposal with design contracts.
- [docs/mctl-composite.md](mctl-composite.md) — irisctl ↔ ydbctl
  side-by-side, 88 operations classified.
- [src/ydbctl/rpc.py](../src/ydbctl/rpc.py) `METHODS` — canonical
  list of every JSON-RPC method.
- [src/ydbctl/commands/which.py](../src/ydbctl/commands/which.py)
  `OPERATIONS` — registry of every subcommand's underlying
  mechanism, used by `ydbctl which`.

### YottaDB official documentation

- [Administration & Operations Guide](https://docs.yottadb.com/AdminOpsGuide/index.html)
- [Basic Operations (env vars, binaries)](https://docs.yottadb.com/AdminOpsGuide/basicops.html)
- [MUPIP — Database Management Tool](https://docs.yottadb.com/AdminOpsGuide/dbmgmt.html)
- [GDE — Global Directory Editor](https://docs.yottadb.com/AdminOpsGuide/gde.html)
- [Journaling](https://docs.yottadb.com/AdminOpsGuide/ydbjournal.html)
- [Replication](https://docs.yottadb.com/AdminOpsGuide/dbrepl.html)
- [Containers](https://docs.yottadb.com/AdminOpsGuide/containers.html)

### Sibling tools

- [irisctl](https://github.com/rafael5/irisctl) — same wrapper
  pattern for IRIS Community Edition.
- [docker-vista-fork](https://github.com/rafael5/docker-vista-fork)
  — Rafael's fork of WorldVistA's docker-vista, where the VistA
  layer commands' helper scripts originate.
