"""`ydbctl locks show / clear` — view/clear active M LOCKs via `lke`."""

from __future__ import annotations

import argparse
from typing import Any

from ydbctl.config import Profile
from ydbctl.output import ErrorCode, error_envelope, success_envelope
from ydbctl.ydb_exec import YdbError, ydb_run


def show(profile: Profile, *, region: str = "*",
         timeout: float = 30.0) -> dict[str, Any]:
    """Run `lke show -all -region=<R>` and return the raw lock report."""
    cmd = f"echo 'show -all -region={region}\nexit\n' | lke"
    try:
        res = ydb_run(profile, cmd, timeout=timeout)
    except YdbError as e:
        return error_envelope("locks", code=ErrorCode.YDB_ERROR, message=str(e))
    out = res["stdout"]

    locks_present = "NO LOCK" not in out.upper() and "<NO LOCKS>" not in out.upper()
    # Count any `^LOCKNAME` pattern occurrences as a rough indicator
    lock_lines = [
        line for line in out.splitlines()
        if line.startswith(" ") and ("^" in line or "PID" in line)
    ]
    return success_envelope("locks", {
        "region": region,
        "any_locks": bool(lock_lines) and locks_present,
        "lock_lines": lock_lines,
        "raw": out,
    })


def clear(profile: Profile, *, region: str = "*", yes: bool = False,
          dry_run: bool = False, timeout: float = 30.0) -> dict[str, Any]:
    """Run `lke clear -all -region=<R>` (mutating). Requires --yes."""
    if not yes and not dry_run:
        return error_envelope(
            "locks", code=ErrorCode.USAGE,
            message="clearing locks is mutating; pass --yes to confirm or "
                    "--dry-run to preview",
        )

    cmd_line = f"clear -all -nointeractive -region={region}"
    if dry_run:
        return success_envelope("locks", {
            "region": region, "dry_run": True,
            "lke_input": cmd_line,
        })

    cmd = f"echo '{cmd_line}\nexit\n' | lke"
    try:
        res = ydb_run(profile, cmd, timeout=timeout)
    except YdbError as e:
        return error_envelope("locks", code=ErrorCode.YDB_ERROR, message=str(e))
    return success_envelope("locks", {
        "region": region,
        "cleared": True,
        "raw": res["stdout"],
    })


def dispatch(args: argparse.Namespace, profile: Profile) -> dict[str, Any]:
    sub = getattr(args, "locks_sub", None)
    if sub == "show":
        return show(profile, region=getattr(args, "region", "*"))
    if sub == "clear":
        return clear(
            profile,
            region=getattr(args, "region", "*"),
            yes=getattr(args, "yes", False),
            dry_run=getattr(args, "dry_run", False),
        )
    return error_envelope(
        "locks", code=ErrorCode.USAGE,
        message="locks needs a sub-verb: show | clear",
    )
