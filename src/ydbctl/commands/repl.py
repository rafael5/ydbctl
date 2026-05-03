"""`ydbctl repl` — replication via `mupip replicate -source/-receiver/-instance`.

Phase 5. Replication is one of YottaDB's most-configured features but
also the one most callers will leave unconfigured. Every status-style
subcommand (`source checkhealth`, `source showbacklog`, etc.) detects
the unconfigured state cleanly via `REPLINSTACC` and returns a
`not_found` envelope with hints rather than a raw mupip error.
"""

from __future__ import annotations

import argparse
from typing import Any

from ydbctl.config import Profile
from ydbctl.output import ErrorCode, error_envelope, success_envelope
from ydbctl.ydb_exec import YdbError, mupip

_NOT_CONFIGURED_HINT = (
    "no replication instance configured. Run `ydbctl repl instance create "
    "--root-primary` (or --propagate-primary) to bootstrap one."
)


def _is_unconfigured(message: str) -> bool:
    return ("REPLINSTACC" in message
            or "could not get file id" in message
            or "No such file or directory" in message)


def _wrap(label: str, fn) -> dict[str, Any]:
    """Common error mapping for mupip replicate calls."""
    try:
        out = fn()
    except YdbError as e:
        msg = str(e)
        if _is_unconfigured(msg):
            return error_envelope(
                "repl",
                code=ErrorCode.NOT_FOUND,
                message=f"{label}: replication not configured",
                hint=_NOT_CONFIGURED_HINT,
            )
        return error_envelope(
            "repl", code=ErrorCode.YDB_ERROR,
            message=f"{label}: {msg}",
        )
    return success_envelope("repl", {"label": label, "raw": out})


# ----------------- source -----------------


def source_checkhealth(profile: Profile) -> dict[str, Any]:
    return _wrap("source-checkhealth",
                 lambda: mupip(profile, ["replicate", "-source",
                                          "-checkhealth"]))


def source_showbacklog(profile: Profile) -> dict[str, Any]:
    return _wrap("source-showbacklog",
                 lambda: mupip(profile, ["replicate", "-source",
                                          "-showbacklog"]))


def source_start(
    profile: Profile, *, port: int, log: str | None = None,
    secondary: str | None = None,
) -> dict[str, Any]:
    args = ["replicate", "-source", "-start", f"-port={port}"]
    if log:
        args.append(f"-log={log}")
    if secondary:
        args.append(f"-secondary={secondary}")
    return _wrap("source-start",
                 lambda: mupip(profile, args, timeout=30.0))


def source_shutdown(
    profile: Profile, *, timeout_secs: int = 30,
) -> dict[str, Any]:
    return _wrap("source-shutdown",
                 lambda: mupip(profile,
                                ["replicate", "-source", "-shutdown",
                                 f"-timeout={timeout_secs}"],
                                timeout=float(timeout_secs) + 30))


# ----------------- receiver -----------------


def receiver_checkhealth(profile: Profile) -> dict[str, Any]:
    return _wrap("receiver-checkhealth",
                 lambda: mupip(profile, ["replicate", "-receiver",
                                          "-checkhealth"]))


def receiver_start(
    profile: Profile, *, listenport: int, log: str | None = None,
) -> dict[str, Any]:
    args = ["replicate", "-receiver", "-start",
            f"-listenport={listenport}"]
    if log:
        args.append(f"-log={log}")
    return _wrap("receiver-start",
                 lambda: mupip(profile, args, timeout=30.0))


def receiver_shutdown(
    profile: Profile, *, timeout_secs: int = 30,
) -> dict[str, Any]:
    return _wrap("receiver-shutdown",
                 lambda: mupip(profile,
                                ["replicate", "-receiver", "-shutdown",
                                 f"-timeout={timeout_secs}"],
                                timeout=float(timeout_secs) + 30))


# ----------------- instance -----------------


def instance_create(
    profile: Profile, *,
    name: str,
    root_primary: bool = False,
    propagate_primary: bool = False,
) -> dict[str, Any]:
    if root_primary == propagate_primary:
        return error_envelope(
            "repl", code=ErrorCode.USAGE,
            message="instance create needs exactly one of "
                    "--root-primary or --propagate-primary",
        )
    args = ["replicate", "-instance", "-create", f"-name={name}"]
    if root_primary:
        args.append("-rootprimary")
    else:
        args.append("-propagateprimary")
    return _wrap("instance-create",
                 lambda: mupip(profile, args, timeout=30.0))


# ----------------- rollback -----------------


def rollback(
    profile: Profile, *,
    fetchresync_port: int | None = None,
    yes: bool = False,
) -> dict[str, Any]:
    if not yes:
        return error_envelope(
            "repl", code=ErrorCode.USAGE,
            message="rollback is destructive; pass --yes to confirm",
        )
    args = ["journal", "-rollback", "-backward", "-noverify"]
    if fetchresync_port is not None:
        args.append(f"-fetchresync={fetchresync_port}")
    args.append("*")
    return _wrap("rollback",
                 lambda: mupip(profile, args, timeout=120.0))


# ----------------- dispatch -----------------


def dispatch(args: argparse.Namespace, profile: Profile) -> dict[str, Any]:
    sub = getattr(args, "repl_sub", None)
    sub_action = getattr(args, "repl_action", None)

    if sub == "source":
        if sub_action == "checkhealth":
            return source_checkhealth(profile)
        if sub_action == "showbacklog":
            return source_showbacklog(profile)
        if sub_action == "start":
            return source_start(profile, port=args.port,
                                 log=getattr(args, "log", None),
                                 secondary=getattr(args, "secondary", None))
        if sub_action == "stop" or sub_action == "shutdown":
            return source_shutdown(profile,
                                    timeout_secs=getattr(args, "timeout_secs", 30))
    elif sub == "receiver":
        if sub_action == "checkhealth":
            return receiver_checkhealth(profile)
        if sub_action == "start":
            return receiver_start(profile, listenport=args.listenport,
                                   log=getattr(args, "log", None))
        if sub_action == "stop" or sub_action == "shutdown":
            return receiver_shutdown(profile,
                                      timeout_secs=getattr(args, "timeout_secs", 30))
    elif sub == "instance":
        if sub_action == "create":
            return instance_create(
                profile, name=args.name,
                root_primary=getattr(args, "root_primary", False),
                propagate_primary=getattr(args, "propagate_primary", False),
            )
    elif sub == "rollback":
        return rollback(
            profile,
            fetchresync_port=getattr(args, "fetchresync", None),
            yes=getattr(args, "yes", False),
        )

    return error_envelope(
        "repl", code=ErrorCode.USAGE,
        message="repl needs source / receiver / instance / rollback "
                "+ an action",
        hint="example: ydbctl repl source checkhealth",
    )
