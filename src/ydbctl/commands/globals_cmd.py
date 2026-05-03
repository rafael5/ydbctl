"""`ydbctl globals show / export`.

Sub-verbs:
- show NAME       — `yottadb -run %XCMD 'ZW ^NAME'` (subtree dump)
- export NAME     — `mupip extract -select=^NAME -format=ZWR` to a file
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from ydbctl.config import Profile
from ydbctl.docker_api import DockerError, cp_from_container
from ydbctl.output import ErrorCode, error_envelope, success_envelope
from ydbctl.ydb_exec import YdbError, mupip, yottadb_xcmd


def show(profile: Profile, *, name: str) -> dict[str, Any]:
    """Return the contents of ^NAME via ZWRITE.

    `ZWRITE` raises `GVUNDEF` on undefined globals — we guard with
    `IF $DATA(^X)` so undefined globals return cleanly with count=0.
    The full `ZWRITE` keyword is required (the `ZW` abbreviation does
    not emit output in r2.07).
    """
    glob_ref = name if name.startswith("^") else f"^{name}"
    code = f'IF $DATA({glob_ref}) ZWRITE {glob_ref}'
    try:
        out = yottadb_xcmd(profile, code)
    except YdbError as e:
        return error_envelope("globals", code=ErrorCode.YDB_ERROR, message=str(e))

    lines = [line for line in out.splitlines() if line]
    if not lines:
        return success_envelope("globals", {
            "name": glob_ref, "lines": [], "count": 0,
            "note": "global has no defined nodes",
        })

    return success_envelope("globals", {
        "name": glob_ref,
        "lines": lines,
        "count": len(lines),
    })


def export(
    profile: Profile,
    *,
    name: str,
    to: Path | None = None,
    format_: str = "ZWR",
) -> dict[str, Any]:
    """Extract ^NAME to a host file via `mupip extract`."""
    glob_ref = name if name.startswith("^") else f"^{name}"
    container_dst = f"/tmp/irisctl-export-{glob_ref.lstrip('^')}.zwr"

    fmt = format_.upper()
    if fmt not in ("ZWR", "GO", "BINARY", "B"):
        return error_envelope(
            "globals",
            code=ErrorCode.USAGE,
            message=f"unknown format {format_!r}; pick ZWR, GO, or BINARY",
        )

    # mupip extract refuses to overwrite an existing file; remove first.
    from ydbctl.ydb_exec import ydb_run
    ydb_run(profile, f"rm -f {container_dst}")

    try:
        mupip(profile, [
            "extract",
            f"-format={fmt}",
            f"-select={glob_ref}",
            container_dst,
        ])
    except YdbError as e:
        return error_envelope(
            "globals", code=ErrorCode.YDB_ERROR,
            message=f"mupip extract failed: {e}",
        )

    host_dst = Path(to) if to is not None else (
        Path.cwd() / f"{glob_ref.lstrip('^')}.zwr"
    )
    host_dst.parent.mkdir(parents=True, exist_ok=True)

    try:
        cp_from_container_path(profile.container, container_dst, str(host_dst))
    except DockerError as e:
        return error_envelope(
            "globals", code=ErrorCode.DOCKER_ERROR,
            message=f"docker cp failed: {e}",
        )

    size = host_dst.stat().st_size if host_dst.exists() else 0
    return success_envelope("globals", {
        "name": glob_ref,
        "format": fmt,
        "container_path": container_dst,
        "host_path": str(host_dst),
        "size_bytes": size,
    })


def cp_from_container_path(container: str, src: str, dst: str) -> None:
    """Wrap docker_api.cp_from_container; safe to swap if signature drifts."""
    cp_from_container(container, src, dst)


def dispatch(args: argparse.Namespace, profile: Profile) -> dict[str, Any]:
    sub = getattr(args, "globals_sub", None)
    if sub == "show":
        return show(profile, name=args.name)
    if sub == "export":
        return export(
            profile,
            name=args.name,
            to=getattr(args, "to", None),
            format_=getattr(args, "format", "ZWR"),
        )
    return error_envelope(
        "globals",
        code=ErrorCode.USAGE,
        message="globals needs a sub-verb: show | export",
        hint="example: ydbctl globals show ^IRISCTLTEST",
    )
