"""`ydbctl which [OP]` — explain underlying mechanism for a subcommand."""

from __future__ import annotations

from typing import Any

from ydbctl.config import Profile
from ydbctl.output import ErrorCode, error_envelope, success_envelope

OPERATIONS: dict[str, dict[str, Any]] = {
    "status": {
        "mechanism": "docker inspect + version + ipc + ports composite",
        "underlying": "(see version, ipc, ports)",
    },
    "version": {
        "mechanism": "docker exec yottadb -version (sources ydb_env_set)",
        "underlying": "docker exec {container} bash -c "
                      "'. {ydb_dist}/ydb_env_set; yottadb -version'",
    },
    "ports": {
        "mechanism": "docker inspect + host TCP probe",
        "underlying": "docker inspect {container} + "
                      "connect({host}, 9080/9081/1337/6789)",
    },
    "env": {
        "mechanism": "docker exec env after ydb_env_set",
        "underlying": "docker exec {container} bash -c "
                      "'. {ydb_dist}/ydb_env_set; env | grep -E ^(ydb_|gtm)'",
    },
    "regions": {
        "mechanism": "docker exec mumps -run GDE with `show` on stdin",
        "underlying": "echo show | docker exec -i {container} bash -c "
                      "'. {ydb_dist}/ydb_env_set; mumps -run GDE'",
    },
    "files": {
        "mechanism": "docker exec find under $ydb_dir for .gld/.dat/.mjl/.repl",
        "underlying": "docker exec {container} bash -c "
                      "'. {ydb_dist}/ydb_env_set; find $ydb_dir -type f ...'",
    },
    "dbinfo": {
        "mechanism": "docker exec mupip dumpfhead -file <DAT> + parser",
        "underlying": "docker exec {container} bash -c "
                      "'. {ydb_dist}/ydb_env_set; mupip dumpfhead -file <DAT>'",
    },
    "ipc": {
        "mechanism": "docker exec ipcs -m / ipcs -s",
        "underlying": "docker exec {container} ipcs -m; ipcs -s",
    },
    "logs": {
        "mechanism": "docker exec mupip journal -show -backward (head N)",
        "underlying": "docker exec {container} bash -c "
                      "'. {ydb_dist}/ydb_env_set; mupip journal -show -backward "
                      "$ydb_dir/$ydb_rel/g/yottadb.mjl | head -N'",
    },
    "health": {
        "mechanism": "composite (status + ipc) → green/yellow verdict",
        "underlying": "(see status, ipc)",
    },
    "which": {
        "mechanism": "lookup in OPERATIONS registry",
        "underlying": "ydbctl/commands/which.py",
    },
    # ---- Phase 2 ----
    "exec": {
        "mechanism": "yottadb -run %XCMD '<m-code>' (default) or "
                      "yottadb -direct heredoc with HALT injection (--direct)",
        "underlying": "docker exec [-i] {container} bash -c "
                      "'. {ydb_dist}/ydb_env_set; yottadb -run %XCMD <code>'",
    },
    "sql": {
        "mechanism": "octo CLI piped on stdin (requires Octo install)",
        "underlying": "docker exec {container} bash -c "
                      "'. {ydb_dist}/ydb_env_set; "
                      "echo <sql> | {ydb_dist}/plugin/bin/octo'",
    },
    "shell": {
        "mechanism": "execvp into docker exec -it yottadb -direct",
        "underlying": "docker exec -it {container} bash -c "
                      "'. {ydb_dist}/ydb_env_set; yottadb -direct'",
    },
    "globals": {
        "mechanism": "show: yottadb -run %XCMD 'IF $D(^X) ZWRITE ^X'  |  "
                      "export: mupip extract -format=ZWR -select=^X + docker cp",
        "underlying": "(see exec for show; mupip + docker cp for export)",
    },
}


def _format(template: str, profile: Profile) -> str:
    return template.format(
        host=profile.host, container=profile.container,
        ydb_dist=profile.ydb_dist, data_dir=str(profile.data_dir),
    )


def describe(op: str, profile: Profile) -> dict[str, Any] | None:
    spec = OPERATIONS.get(op)
    if spec is None:
        return None
    return {
        "op": op,
        "mechanism": spec["mechanism"],
        "underlying": _format(spec["underlying"], profile),
    }


def run(profile: Profile, *, op: str | None) -> dict[str, Any]:
    if op is None:
        rows = [describe(name, profile) for name in sorted(OPERATIONS)]
        return success_envelope("which", {
            "operations": [r for r in rows if r is not None],
            "count": len(OPERATIONS),
        })
    rec = describe(op, profile)
    if rec is None:
        return error_envelope(
            "which",
            code=ErrorCode.NOT_FOUND,
            message=f"unknown operation: {op!r}",
            hint=f"try one of: {', '.join(sorted(OPERATIONS))}",
        )
    return success_envelope("which", rec)
