"""`ydbctl shell` — interactive `yottadb -direct` proxy.

Pure pass-through: `os.execvp` into `docker exec -it <container> bash
-c '. ydb_env_set; yottadb -direct'`. The user's terminal connects
directly. `--dry-run` returns the planned argv as an envelope instead.
"""

from __future__ import annotations

import os
from typing import Any

from ydbctl.config import Profile
from ydbctl.docker_api import container_exists
from ydbctl.output import ErrorCode, error_envelope, success_envelope


def build_exec_argv(profile: Profile) -> list[str]:
    inner = (
        f". {profile.ydb_dist}/ydb_env_set >/dev/null 2>&1 && "
        "exec yottadb -direct"
    )
    return [
        "docker", "exec", "-it", profile.container,
        "bash", "-c", inner,
    ]


def run(
    profile: Profile,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    if not container_exists(profile.container):
        return error_envelope(
            "shell",
            code=ErrorCode.INSTANCE_NOT_RUNNING,
            message=f"container {profile.container!r} not found",
        )

    argv = build_exec_argv(profile)

    if dry_run:
        return success_envelope("shell", {"argv": argv, "dry_run": True})

    os.execvp(argv[0], argv)
    return error_envelope(
        "shell", code=ErrorCode.DOCKER_ERROR,
        message="execvp returned (this should not happen)",
    )
