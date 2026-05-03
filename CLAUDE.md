# ydbctl — Claude Project Context

## What this project is

A programmer/AI-friendly CLI wrapper for YottaDB Docker containers.
Hides the patchwork of `docker exec`, `mupip` / `lke` / `gde`
invocations, IPC bookkeeping, and direct-mode heredocs behind a
deterministic, JSON-first surface.

Sibling project: [`irisctl`](https://github.com/rafael5/irisctl) for
the IRIS Community Edition Docker container — same envelope shape,
same subcommand naming where concepts overlap.

Companion docs in `docs/`:
- `ydb-cli-surface.md` — the surface this wraps
- `ydb-cli-plan.md` — the proposal & implementation plan (5 phases)
- `mctl-composite.md` — irisctl ↔ ydbctl side-by-side

## Test target — the live ydb-test container

**Every command is tested against a real YottaDB container** named
`ydb-test`. Per the project plan, "real container only — no mocking".

Bring it up with:

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
- `%ydbocto.dat`, `%ydbaim.dat` (plugin-installed regions)

Tests are marked `integration` if they need the live container; run
just those with `make test-int`. Unit tests (parsers, output
formatting) run via `make test-unit` without container deps.

## Dev workflow

```bash
make install      # create .venv, install deps + pre-commit hooks
make test         # all tests (integration + unit)
make test-unit    # parser/output tests only — no container needed
make test-int     # integration tests against live ydb-test container
make watch        # TDD mode: auto-rerun on file save
make cov          # pytest with coverage report
make check        # lint + mypy + cov (full gate)
make format       # ruff format
make push         # check + git push
```

## Architecture (per docs/ydb-cli-plan.md §7.2)

```
src/ydbctl/
├── cli.py              # argparse tree + dispatch
├── config.py           # profiles + auth + ydb_dist defaults
├── output.py           # JSON envelope, human renderer
├── docker_api.py       # docker inspect / exec / start / stop
├── ydb_exec.py         # docker exec + ydb_env_set sourcing
├── parsers/
│   ├── dumpfhead.py    # mupip dumpfhead -file <dat> → JSON
│   ├── version.py      # yottadb -version → JSON
│   └── ipcs.py         # ipcs -m / -s → JSON
└── commands/
    ├── status.py
    ├── version.py
    ├── ports.py
    ├── env.py
    ├── regions.py
    ├── files.py
    ├── dbinfo.py
    ├── ipc.py
    ├── logs.py
    └── health.py
```

## Output contract (mirrors irisctl)

Every command emits the same JSON envelope (or pretty table with `--human`):

```json
{"v": 1, "ok": true, "command": "regions", "data": {...}, "warnings": []}
{"v": 1, "ok": false, "command": "ipc",
 "error": {"code": "ipc_orphans", "message": "...",
           "hint": "...", "ref": "..."}}
```

Exit codes: 0=ok, 1=internal, 2=usage, 3=instance_not_running,
4=ipc_orphans, 5=auth_required/auth_failed, 6=not_found,
7=ydb_error, 8=docker_error, 9=network_error.

(Note: 4 is `ipc_orphans` here, not IRIS's `license_exhausted`.)

## Phasing

| Phase | Subcommands | Status |
|---|---|---|
| 1 | status, version, ports, env, regions, files, dbinfo, ipc, logs, health | **in progress** |
| 2 | exec, sql, shell, globals (LU-free; YDB has no LU concept) | not started |
| 3 | maintenance: backup, restore, integ, reorg, freeze, locks, rundown, recover | not started |
| 4 | services: gui, rocto, web, gtcm + VistA layer if profile.vista=true | not started |
| 5 | replication, polish | not started (pipx skipped) |

## Code style

- TDD — write tests first
- Ruff for format + lint (no black)
- Line length 88
- Logging not print() in library code
- No mocks unless unavoidable (per `~/.claude/CLAUDE.md`)
- Hobbyist project — keep solutions simple and direct
- Edit existing files in preference to creating new ones
