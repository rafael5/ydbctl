"""`ydbctl backup` — `mupip backup -bytestream <region> <out-file>`.

Online by default; the wrapper picks a per-region backup filename
under the user-supplied directory.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ydbctl.config import Profile
from ydbctl.docker_api import DockerError, cp_from_container
from ydbctl.output import ErrorCode, error_envelope, success_envelope
from ydbctl.ydb_exec import YdbError, mupip, ydb_run

_BACKUPDB_RE = re.compile(
    r"%YDB-I-BACKUPDBFILE,\s*DB file\s+(\S+)\s+backed up in file\s+(\S+)"
)
_BACKUP_OK_RE = re.compile(r"%YDB-I-BACKUPSUCCESS")


def _default_out_dir() -> Path:
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path.home() / "data" / "backups" / f"ydb-test-{ts}"


def run(
    profile: Profile,
    *,
    region: str = "DEFAULT",
    to: Path | None = None,
    online: bool = True,
    dry_run: bool = False,
    timeout: float = 600.0,
) -> dict[str, Any]:
    out_dir = Path(to) if to is not None else _default_out_dir()
    out_dir.mkdir(parents=True, exist_ok=True)

    # In-container backup target — region.bk file under /tmp
    container_bk = f"/tmp/ydbctl-backup-{region.lower()}.bk"
    args = ["backup"]
    if not online:
        args.append("-online=FALSE")
    args.extend(["-bytestream", region, container_bk])

    if dry_run:
        return success_envelope("backup", {
            "region": region,
            "out_dir": str(out_dir),
            "container_path": container_bk,
            "online": online,
            "dry_run": True,
            "steps": [
                f"docker exec {profile.container} bash -c "
                f"'. {profile.ydb_dist}/ydb_env_set; rm -f {container_bk}; "
                f"mupip {' '.join(args)}'",
                f"docker cp {profile.container}:{container_bk} {out_dir}/",
            ],
        })

    # mupip backup refuses to overwrite — clean up first
    ydb_run(profile, f"rm -f {container_bk}")

    try:
        ydb_out = mupip(profile, args, timeout=timeout)
    except YdbError as e:
        return error_envelope("backup", code=ErrorCode.YDB_ERROR, message=str(e))

    if not _BACKUP_OK_RE.search(ydb_out):
        return error_envelope(
            "backup", code=ErrorCode.YDB_ERROR,
            message=f"mupip backup did not report SUCCESS:\n{ydb_out[-400:]}",
        )

    # Copy out
    host_bk = out_dir / f"{region.lower()}.bk"
    try:
        cp_from_container(profile.container, container_bk, str(host_bk))
    except DockerError as e:
        return error_envelope(
            "backup", code=ErrorCode.DOCKER_ERROR,
            message=f"docker cp failed: {e}",
        )

    size = host_bk.stat().st_size if host_bk.exists() else 0
    db_pairs = [
        {"db_file": m.group(1), "backup_file": m.group(2)}
        for m in _BACKUPDB_RE.finditer(ydb_out)
    ]

    return success_envelope("backup", {
        "region": region,
        "host_path": str(host_bk),
        "size_bytes": size,
        "online": online,
        "container_path": container_bk,
        "db_files": db_pairs,
    })
