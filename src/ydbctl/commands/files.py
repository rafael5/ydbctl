"""`ydbctl files` — enumerate .gld / .dat / .mjl / .repl under ydb_dir."""

from __future__ import annotations

from typing import Any

from ydbctl.config import Profile
from ydbctl.output import ErrorCode, error_envelope, success_envelope
from ydbctl.ydb_exec import YdbError, ydb_run


def run(profile: Profile) -> dict[str, Any]:
    cmd = (
        "find $ydb_dir -type f "
        "\\( -name '*.gld' -o -name '*.dat' -o -name '*.mjl' "
        "-o -name '*.mjl_*' -o -name '*.repl' \\) "
        '-printf "%p\\t%s\\t%TY-%Tm-%Td\\n"'
    )
    try:
        res = ydb_run(profile, cmd)
    except YdbError as e:
        return error_envelope("files", code=ErrorCode.YDB_ERROR, message=str(e))

    files: list[dict[str, Any]] = []
    for line in res["stdout"].splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        path, size, mtime = parts[0], parts[1], parts[2]
        ext = path.rsplit(".", 1)[-1] if "." in path else ""
        files.append({
            "path": path,
            "size_bytes": int(size) if size.isdigit() else 0,
            "mtime": mtime,
            "kind": _kind_for(ext, path),
        })

    return success_envelope("files", {
        "files": sorted(files, key=lambda r: r["path"]),
        "count": len(files),
    })


def _kind_for(ext: str, path: str) -> str:
    if ext == "gld":
        return "global_directory"
    if ext == "dat":
        return "database"
    if ext == "repl":
        return "replication_instance"
    if ".mjl" in path:
        return "journal"
    return "other"
