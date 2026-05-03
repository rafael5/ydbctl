"""JSON-RPC 2.0 single-process mode for ydbctl.

`ydbctl rpc` reads newline-delimited JSON-RPC 2.0 requests on stdin
and writes responses on stdout. Designed for AI agents that want a
persistent process to talk to instead of spawning ~30 distinct CLI
invocations.

Mirrors irisctl/rpc.py — same JSON-RPC error codes, same notification
semantics. Method names use underscores in place of subcommand spaces
(e.g. `globals_show`, `locks_show`, `vista_rpcbroker`).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import IO, Any, Callable

from ydbctl.commands import (
    backup as cmd_backup,
)
from ydbctl.commands import (
    dbinfo as cmd_dbinfo,
)
from ydbctl.commands import (
    env as cmd_env,
)
from ydbctl.commands import (
    exec_cmd as cmd_exec,
)
from ydbctl.commands import (
    files as cmd_files,
)
from ydbctl.commands import (
    freeze as cmd_freeze,
)
from ydbctl.commands import (
    globals_cmd as cmd_globals,
)
from ydbctl.commands import (
    health as cmd_health,
)
from ydbctl.commands import (
    integ as cmd_integ,
)
from ydbctl.commands import (
    ipc as cmd_ipc,
)
from ydbctl.commands import (
    locks as cmd_locks,
)
from ydbctl.commands import (
    logs as cmd_logs,
)
from ydbctl.commands import (
    ports as cmd_ports,
)
from ydbctl.commands import (
    recover as cmd_recover,
)
from ydbctl.commands import (
    regions as cmd_regions,
)
from ydbctl.commands import (
    reorg as cmd_reorg,
)
from ydbctl.commands import (
    repl as cmd_repl,
)
from ydbctl.commands import (
    restore as cmd_restore,
)
from ydbctl.commands import (
    rundown as cmd_rundown,
)
from ydbctl.commands import (
    shell as cmd_shell,
)
from ydbctl.commands import (
    sql as cmd_sql,
)
from ydbctl.commands import (
    status as cmd_status,
)
from ydbctl.commands import (
    version as cmd_version,
)
from ydbctl.commands import (
    vista as cmd_vista,
)
from ydbctl.commands import (
    which as cmd_which,
)
from ydbctl.config import Profile

# JSON-RPC 2.0 standard error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


def _build_registry() -> dict[str, Callable[..., dict[str, Any]]]:
    return {
        # Phase 1 — read-only
        "status": lambda p: cmd_status.run(p),
        "version": lambda p: cmd_version.run(p),
        "ports": lambda p: cmd_ports.run(p),
        "env": lambda p, name=None: cmd_env.run(p, name=name),
        "regions": lambda p: cmd_regions.run(p),
        "files": lambda p: cmd_files.run(p),
        "dbinfo": lambda p, region=None, file=None, full=False:
                  cmd_dbinfo.run(p, region=region, file=file, full=full),
        "ipc": lambda p: cmd_ipc.run(p),
        "logs": lambda p, tail=50: cmd_logs.run(p, tail=tail),
        "health": lambda p: cmd_health.run(p),
        "which": lambda p, op=None: cmd_which.run(p, op=op),
        # Phase 2 — execution
        "exec": lambda p, code=None, file=None, run_entry=None,
                run_args=None, direct=False:
                cmd_exec.run(p, code=code,
                              file=Path(file) if file else None,
                              run_entry=run_entry, run_args=run_args,
                              direct=direct),
        "sql": lambda p, statement=None, file=None:
               cmd_sql.run(p, statement=statement,
                            file=Path(file) if file else None),
        "shell": lambda p: cmd_shell.run(p, dry_run=True),
        "globals_show": lambda p, name: cmd_globals.show(p, name=name),
        "globals_export": lambda p, name, to=None, format="ZWR":
                          cmd_globals.export(p, name=name,
                                              to=Path(to) if to else None,
                                              format_=format),
        # Phase 3 — maintenance
        "integ": lambda p, region="*", full=False:
                 cmd_integ.run(p, region=region, full=full),
        "reorg": lambda p, region="*", truncate=False:
                 cmd_reorg.run(p, region=region, truncate=truncate),
        "freeze": lambda p, on=False, off=False, region="*":
                  cmd_freeze.run(p, on=on, off=off, region=region),
        "locks_show": lambda p, region="*":
                      cmd_locks.show(p, region=region),
        "locks_clear": lambda p, region="*", yes=False, dry_run=False:
                       cmd_locks.clear(p, region=region, yes=yes,
                                        dry_run=dry_run),
        "rundown": lambda p, region="*": cmd_rundown.run(p, region=region),
        "recover": lambda p, region="*", journal_file=None, backward=True:
                   cmd_recover.run(p, region=region,
                                    journal_file=journal_file,
                                    backward=backward),
        "backup": lambda p, region="DEFAULT", to=None, online=True,
                  dry_run=False:
                  cmd_backup.run(p, region=region,
                                  to=Path(to) if to else None,
                                  online=online, dry_run=dry_run),
        "restore": lambda p, source, target_dat, yes=False, dry_run=False:
                   cmd_restore.run(p, source=Path(source),
                                    target_dat=target_dat, yes=yes,
                                    dry_run=dry_run),
        # Phase 4 — VistA
        "vista_rpcbroker": lambda p, action="status":
                           cmd_vista.rpcbroker(p, action),
        "vista_vistalink": lambda p, action="status":
                           cmd_vista.vistalink(p, action),
        "vista_hl7": lambda p, action="status": cmd_vista.hl7(p, action),
        "vista_journal": lambda p, action: cmd_vista.journal(p, action),
        "vista_ports": lambda p: cmd_vista.ports(p),
        # Phase 5 — replication
        "repl_source_checkhealth": lambda p: cmd_repl.source_checkhealth(p),
        "repl_source_showbacklog": lambda p: cmd_repl.source_showbacklog(p),
        "repl_receiver_checkhealth": lambda p: cmd_repl.receiver_checkhealth(p),
        "repl_instance_create": lambda p, name, root_primary=False,
                                propagate_primary=False:
                                cmd_repl.instance_create(
                                    p, name=name, root_primary=root_primary,
                                    propagate_primary=propagate_primary),
    }


METHODS = _build_registry()


def _rpc_error(req_id: Any, code: int, message: str,
                data: Any = None) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


def _rpc_result(req_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def handle_request(
    req: dict[str, Any],
    profile: Profile,
) -> dict[str, Any] | None:
    """Process one JSON-RPC request; return response or None for notifications."""
    req_id = req.get("id")
    is_notification = "id" not in req

    if req.get("jsonrpc") != "2.0":
        if is_notification:
            return None
        return _rpc_error(req_id, INVALID_REQUEST,
                           "missing or invalid jsonrpc field")

    method = req.get("method")
    if not isinstance(method, str):
        if is_notification:
            return None
        return _rpc_error(req_id, INVALID_REQUEST, "missing method")

    fn = METHODS.get(method)
    if fn is None:
        if is_notification:
            return None
        return _rpc_error(req_id, METHOD_NOT_FOUND,
                           f"method {method!r} not registered",
                           data={"available": sorted(METHODS)})

    raw_params = req.get("params") or {}
    if isinstance(raw_params, list):
        if is_notification:
            return None
        return _rpc_error(req_id, INVALID_PARAMS,
                           "positional params not supported; use object form")

    try:
        result = fn(profile, **raw_params)
    except TypeError as e:
        if is_notification:
            return None
        return _rpc_error(req_id, INVALID_PARAMS, str(e))
    except Exception as e:  # noqa: BLE001
        if is_notification:
            return None
        return _rpc_error(req_id, INTERNAL_ERROR,
                           f"{type(e).__name__}: {e}")

    if is_notification:
        return None
    return _rpc_result(req_id, result)


def serve(
    profile: Profile,
    *,
    stdin: IO[str] | None = None,
    stdout: IO[str] | None = None,
) -> None:
    """Read newline-delimited JSON-RPC requests until EOF."""
    in_stream = stdin if stdin is not None else sys.stdin
    out_stream = stdout if stdout is not None else sys.stdout

    for line in in_stream:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            err = _rpc_error(None, PARSE_ERROR, f"parse error: {e}")
            out_stream.write(json.dumps(err) + "\n")
            out_stream.flush()
            continue

        if not isinstance(req, dict):
            err = _rpc_error(None, INVALID_REQUEST,
                              "request must be a JSON object")
            out_stream.write(json.dumps(err) + "\n")
            out_stream.flush()
            continue

        resp = handle_request(req, profile)
        if resp is None:
            continue
        out_stream.write(json.dumps(resp, separators=(",", ":")) + "\n")
        out_stream.flush()
