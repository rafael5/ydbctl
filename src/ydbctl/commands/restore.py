"""`ydbctl restore` — `mupip restore <bytestream-file> <dat-file>`.

Destructive: replaces the target .dat with the contents of the
bytestream backup. Requires `--yes` to actually run.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ydbctl.config import Profile
from ydbctl.docker_api import DockerError, cp_to_container
from ydbctl.output import ErrorCode, error_envelope, success_envelope
from ydbctl.ydb_exec import YdbError, mupip


def run(
    profile: Profile,
    *,
    source: Path,
    target_dat: str,
    yes: bool = False,
    dry_run: bool = False,
    timeout: float = 600.0,
) -> dict[str, Any]:
    src = Path(source)

    if not src.exists():
        return error_envelope(
            "restore", code=ErrorCode.NOT_FOUND,
            message=f"backup source not found: {src}",
        )

    container_bk = "/tmp/ydbctl-restore-source.bk"

    steps = [
        f"docker cp {src} {profile.container}:{container_bk}",
        f"mupip restore {target_dat} {container_bk}",
    ]
    if dry_run:
        return success_envelope("restore", {
            "source": str(src),
            "target_dat": target_dat,
            "dry_run": True,
            "steps": steps,
        })

    if not yes:
        return error_envelope(
            "restore", code=ErrorCode.USAGE,
            message=("restore is destructive (overwrites target DAT). "
                     "Pass --yes to confirm, or --dry-run to inspect."),
            hint="back up the existing target first if unsure",
        )

    # Stage source into the container
    try:
        cp_to_container(str(src), profile.container, container_bk)
    except DockerError as e:
        return error_envelope("restore", code=ErrorCode.DOCKER_ERROR,
                               message=f"docker cp failed: {e}")

    try:
        out = mupip(profile, ["restore", target_dat, container_bk],
                    timeout=timeout)
    except YdbError as e:
        return error_envelope("restore", code=ErrorCode.YDB_ERROR,
                               message=f"mupip restore failed: {e}")

    return success_envelope("restore", {
        "source": str(src),
        "target_dat": target_dat,
        "container_staged": container_bk,
        "raw": out,
    })
