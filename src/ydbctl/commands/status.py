"""`ydbctl status` — composite container + version + IPC + service-port snapshot."""

from __future__ import annotations

from typing import Any

from ydbctl.commands import ipc as cmd_ipc
from ydbctl.commands import ports as cmd_ports
from ydbctl.commands import version as cmd_version
from ydbctl.config import Profile
from ydbctl.docker_api import DockerError, container_exists, container_state
from ydbctl.output import ErrorCode, error_envelope, success_envelope


def run(profile: Profile) -> dict[str, Any]:
    if not container_exists(profile.container):
        return error_envelope(
            "status",
            code=ErrorCode.INSTANCE_NOT_RUNNING,
            message=f"container {profile.container!r} not found",
        )
    try:
        cstate = container_state(profile.container)
    except DockerError as e:
        return error_envelope("status", code=ErrorCode.DOCKER_ERROR, message=str(e))

    version_env = cmd_version.run(profile)
    ports_env = cmd_ports.run(profile)
    ipc_env = cmd_ipc.run(profile)

    warnings: list[str] = []
    if not cstate["running"]:
        warnings.append("container not running")
    if not version_env["ok"]:
        warnings.append(f"version probe failed: {version_env['error']['message']}")
    if not ipc_env["ok"]:
        warnings.append(f"ipc probe failed: {ipc_env['error']['message']}")
    if ipc_env["ok"]:
        warnings.extend(ipc_env.get("warnings") or [])

    return success_envelope("status", {
        "container": cstate,
        "ydb_release": (version_env["data"].get("ydb_release", "")
                         if version_env["ok"] else None),
        "listeners": ports_env["data"] if ports_env["ok"] else [],
        "ipc": (ipc_env["data"] if ipc_env["ok"] else None),
    }, warnings=warnings)
