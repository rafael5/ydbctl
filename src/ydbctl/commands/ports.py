"""`ydbctl ports` — listener reachability for the optional services.

Unlike IRIS, vanilla YottaDB has NO listener by default. The ports
this command checks (9080 GUI, 9081 GUI-stats, 1337 ROcto, 6789 GT.CM)
are all opt-in and may be closed even on a healthy install.
"""

from __future__ import annotations

from typing import Any

from ydbctl.config import Profile
from ydbctl.docker_api import (
    DockerError,
    container_exists,
    list_published_ports,
    tcp_open,
)
from ydbctl.output import ErrorCode, error_envelope, success_envelope


def run(profile: Profile) -> dict[str, Any]:
    if not container_exists(profile.container):
        return error_envelope(
            "ports",
            code=ErrorCode.INSTANCE_NOT_RUNNING,
            message=f"container {profile.container!r} not found",
        )
    try:
        published = list_published_ports(profile.container)
    except DockerError as e:
        return error_envelope("ports", code=ErrorCode.DOCKER_ERROR, message=str(e))

    expected = {
        profile.gui_port: "ydb_gui",
        profile.gui_stats_port: "ydb_gui_stats",
        profile.rocto_port: "rocto",
        profile.gtcm_port: "gtcm",
    }

    by_host: dict[int, dict[str, Any]] = {}
    for binding in published:
        if binding.get("host_port") is not None:
            by_host[binding["host_port"]] = binding

    rows: list[dict[str, Any]] = []
    for port, role in expected.items():
        entry: dict[str, Any] | None = by_host.get(port)
        if entry is None:
            rows.append({
                "role": role, "container_port": None,
                "host_port": port, "reachable": False,
                "note": "not published by container",
            })
            continue
        rows.append({
            "role": role,
            "container_port": entry.get("container_port"),
            "host_port": port,
            "reachable": tcp_open(profile.host, port),
        })

    # No warnings on unreachable — these listeners are opt-in.
    return success_envelope("ports", rows)
