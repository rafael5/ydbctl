"""`ydbctl vista` — wrappers for the docker-vista-fork VistA-on-YottaDB layer.

Phase 4 VistA-only — assumes the container is built from
docker-vista-fork's `autoInstaller.sh -y …` path, which installs:

- /home/<instance>/bin/rpcbroker.sh   (foreground listener)
- /home/<instance>/bin/vistalink.sh   (foreground listener)
- /home/<instance>/bin/hl7.sh         (foreground listener)
- /home/<instance>/bin/enableJournal.sh / disableJournal.sh / rotateJournal.sh
- /home/<instance>/etc/env            (env-var source for the journal helpers)

Sub-verbs:
- vista rpcbroker / vistalink / hl7   start | stop | status
- vista journal                       enable | disable | rotate
- vista ports                         reachability table for VistA listeners

All vista subcommands are gated by `profile.vista=True`. Without that
flag, they return a `usage` error so they never accidentally execute
against a non-VistA YottaDB container.
"""

from __future__ import annotations

import argparse
from typing import Any

from ydbctl.config import Profile
from ydbctl.docker_api import (
    DockerError,
    container_exists,
    docker_exec,
    tcp_open,
)
from ydbctl.output import ErrorCode, error_envelope, success_envelope
from ydbctl.ydb_exec import YdbError, ydb_run

_SERVICES = {
    "rpcbroker": {"script": "rpcbroker.sh", "port_attr": "vista_rpc_port"},
    "vistalink": {"script": "vistalink.sh", "port_attr": "vista_vistalink_port"},
    "hl7":       {"script": "hl7.sh",       "port_attr": "vista_hl7_port"},
}

_JOURNAL_SCRIPTS = {
    "enable":  "enableJournal.sh",
    "disable": "disableJournal.sh",
    "rotate":  "rotateJournal.sh",
}


def _refuse_when_not_vista(profile: Profile) -> dict[str, Any] | None:
    if profile.vista:
        return None
    return error_envelope(
        "vista",
        code=ErrorCode.USAGE,
        message="vista commands require profile.vista=true",
        hint="set vista=true in ~/.config/ydbctl/config.toml or "
             "switch to a docker-vista-fork YottaDB build",
    )


def _service_status(profile: Profile, service: str) -> dict[str, Any]:
    """status = listener port reachability + process presence (pgrep)."""
    spec = _SERVICES[service]
    port = getattr(profile, spec["port_attr"])
    script = spec["script"]

    reachable = tcp_open(profile.host, port, timeout=1.0)

    # Process presence inside the container
    pgrep_running = False
    try:
        out = docker_exec(profile.container, ["pgrep", "-f", script])
        pgrep_running = bool(out.strip())
    except DockerError:
        # pgrep returns 1 when nothing matches — that's still "not running"
        pgrep_running = False

    return success_envelope("vista", {
        "service": service,
        "script": script,
        "container_path": f"{profile.vista_bin()}/{script}",
        "host_port": port,
        "port_reachable": reachable,
        "process_running": pgrep_running,
        "running": reachable and pgrep_running,
    })


def _service_start(profile: Profile, service: str) -> dict[str, Any]:
    """Start the service script as a background process inside the container."""
    spec = _SERVICES[service]
    script = spec["script"]
    bin_dir = profile.vista_bin()
    full_path = f"{bin_dir}/{script}"

    # Refuse if helper is missing
    try:
        docker_exec(profile.container, ["test", "-x", full_path])
    except DockerError:
        return error_envelope(
            "vista",
            code=ErrorCode.NOT_FOUND,
            message=f"VistA helper not found in container: {full_path}",
            hint="this image isn't built from docker-vista-fork, "
                 "or vista_instance/vista_bin_dir is misconfigured",
        )

    # nohup the script so it survives our docker exec exit
    cmd = (
        f"cd {bin_dir} && "
        f"nohup bash {full_path} >>/tmp/{service}.out 2>&1 < /dev/null & "
        "echo PID=$!"
    )
    try:
        out = docker_exec(profile.container, ["bash", "-c", cmd])
    except DockerError as e:
        return error_envelope(
            "vista", code=ErrorCode.YDB_ERROR,
            message=f"failed to launch {script}: {e}",
        )

    pid = None
    for line in out.splitlines():
        if line.startswith("PID="):
            pid = line[4:].strip()

    return success_envelope("vista", {
        "service": service,
        "script": script,
        "started": True,
        "pid": pid,
        "log": f"/tmp/{service}.out",
    })


def _service_stop(profile: Profile, service: str) -> dict[str, Any]:
    """Stop = pkill -f <script> inside the container."""
    spec = _SERVICES[service]
    script = spec["script"]

    try:
        out = docker_exec(profile.container,
                          ["bash", "-c", f"pkill -f {script} && echo KILLED"])
    except DockerError:
        # pkill returns non-zero when nothing matched — that's "already stopped"
        return success_envelope("vista", {
            "service": service,
            "script": script,
            "stopped": False,
            "note": "no matching process found (already stopped)",
        })
    killed = "KILLED" in out
    return success_envelope("vista", {
        "service": service,
        "script": script,
        "stopped": killed,
    })


def _service_dispatch(
    profile: Profile, service: str, action: str | None,
) -> dict[str, Any]:
    refuse = _refuse_when_not_vista(profile)
    if refuse is not None:
        return refuse
    if not container_exists(profile.container):
        return error_envelope(
            "vista", code=ErrorCode.INSTANCE_NOT_RUNNING,
            message=f"container {profile.container!r} not found",
        )
    if action == "start":
        return _service_start(profile, service)
    if action == "stop":
        return _service_stop(profile, service)
    if action == "status" or action is None:
        return _service_status(profile, service)
    return error_envelope(
        "vista", code=ErrorCode.USAGE,
        message=f"unknown {service} action: {action!r}",
        hint="use start | stop | status",
    )


def rpcbroker(profile: Profile, action: str | None = None) -> dict[str, Any]:
    return _service_dispatch(profile, "rpcbroker", action)


def vistalink(profile: Profile, action: str | None = None) -> dict[str, Any]:
    return _service_dispatch(profile, "vistalink", action)


def hl7(profile: Profile, action: str | None = None) -> dict[str, Any]:
    return _service_dispatch(profile, "hl7", action)


def journal(profile: Profile, action: str) -> dict[str, Any]:
    refuse = _refuse_when_not_vista(profile)
    if refuse is not None:
        return refuse

    if action not in _JOURNAL_SCRIPTS:
        return error_envelope(
            "vista", code=ErrorCode.USAGE,
            message=f"unknown journal action: {action!r}",
            hint=f"use one of: {', '.join(_JOURNAL_SCRIPTS)}",
        )

    script = _JOURNAL_SCRIPTS[action]
    full_path = f"{profile.vista_bin()}/{script}"

    # Source the instance env first (sets gtm_dist, basedir, instance, gtmver)
    cmd = (
        f"source /home/{profile.vista_instance}/etc/env "
        f"&& bash {full_path} 2>&1"
    )
    try:
        res = ydb_run(profile, cmd)
    except YdbError as e:
        return error_envelope(
            "vista", code=ErrorCode.YDB_ERROR,
            message=f"journal {action}: {e}",
        )
    if res["returncode"] != 0:
        return error_envelope(
            "vista", code=ErrorCode.YDB_ERROR,
            message=f"journal {action} exit {res['returncode']}: "
                    f"{(res['stderr'] or res['stdout'])[:300]}",
        )
    return success_envelope("vista", {
        "action": action,
        "script": script,
        "raw": res["stdout"],
    })


def ports(profile: Profile) -> dict[str, Any]:
    """Listener-reachability table for the VistA-specific ports."""
    refuse = _refuse_when_not_vista(profile)
    if refuse is not None:
        return refuse

    rows = [
        {
            "role": "rpcbroker",
            "host_port": profile.vista_rpc_port,
            "reachable": tcp_open(profile.host, profile.vista_rpc_port),
        },
        {
            "role": "vistalink",
            "host_port": profile.vista_vistalink_port,
            "reachable": tcp_open(profile.host, profile.vista_vistalink_port),
        },
        {
            "role": "hl7",
            "host_port": profile.vista_hl7_port,
            "reachable": tcp_open(profile.host, profile.vista_hl7_port),
        },
    ]
    warnings = [
        f"{r['role']} ({r['host_port']}) not reachable"
        for r in rows if not r["reachable"]
    ]
    return success_envelope("vista", {"listeners": rows}, warnings=warnings)


def dispatch(args: argparse.Namespace, profile: Profile) -> dict[str, Any]:
    sub = getattr(args, "vista_sub", None)
    if sub == "rpcbroker":
        return rpcbroker(profile, getattr(args, "action", None))
    if sub == "vistalink":
        return vistalink(profile, getattr(args, "action", None))
    if sub == "hl7":
        return hl7(profile, getattr(args, "action", None))
    if sub == "journal":
        return journal(profile, args.action)
    if sub == "ports":
        return ports(profile)
    return error_envelope(
        "vista", code=ErrorCode.USAGE,
        message="vista needs a sub-verb: rpcbroker | vistalink | hl7 | "
                "journal | ports",
        hint="example: ydbctl vista rpcbroker status",
    )
