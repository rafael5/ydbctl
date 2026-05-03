"""ydbctl CLI entry point.

Mirrors irisctl/cli.py: argparse tree with global flags valid before
or after the subcommand, JSON-first output, --human / --pretty.
"""

from __future__ import annotations

import argparse
import logging
import sys
from types import ModuleType
from typing import Any, Callable

from ydbctl import __version__
from ydbctl.config import load_profile
from ydbctl.output import (
    ErrorCode,
    error_envelope,
    exit_code_for,
    render_human,
    render_json,
)

argcomplete: ModuleType | None
try:
    import argcomplete as _argcomplete  # noqa: I001
    argcomplete = _argcomplete
except ImportError:  # pragma: no cover
    argcomplete = None

log = logging.getLogger(__name__)

CommandRunner = Callable[..., dict[str, Any]]


def _emit(envelope: dict[str, Any], *, args: argparse.Namespace) -> int:
    if getattr(args, "human", False):
        sys.stdout.write(render_human(envelope) + "\n")
    else:
        sys.stdout.write(render_json(envelope, pretty=args.pretty) + "\n")
    sys.stdout.flush()
    if envelope["ok"]:
        return exit_code_for(ErrorCode.OK)
    code = ErrorCode(envelope["error"]["code"])
    return exit_code_for(code)


def _add_global_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--profile", default=argparse.SUPPRESS,
                   help="Profile name from ~/.config/ydbctl/config.toml")
    out = p.add_mutually_exclusive_group()
    out.add_argument("--json", dest="human", action="store_false",
                     default=argparse.SUPPRESS, help="JSON output (default)")
    out.add_argument("--human", dest="human", action="store_true",
                     default=argparse.SUPPRESS,
                     help="Human-readable table output")
    p.add_argument("--pretty", action="store_true",
                   default=argparse.SUPPRESS,
                   help="Pretty-print JSON output")


def _build_parser() -> argparse.ArgumentParser:
    globals_parent = argparse.ArgumentParser(add_help=False)
    _add_global_flags(globals_parent)

    parser = argparse.ArgumentParser(
        prog="ydbctl",
        description=(
            "Programmer/AI-friendly CLI for YottaDB Docker containers."
        ),
        parents=[globals_parent],
    )
    parser.add_argument("--version", action="version",
                        version=f"ydbctl {__version__}")

    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    def _sub(name: str, **kw):
        return sub.add_parser(name, parents=[globals_parent], **kw)

    # Lazy imports
    from ydbctl.commands import dbinfo as cmd_dbinfo
    from ydbctl.commands import env as cmd_env
    from ydbctl.commands import files as cmd_files
    from ydbctl.commands import health as cmd_health
    from ydbctl.commands import ipc as cmd_ipc
    from ydbctl.commands import logs as cmd_logs
    from ydbctl.commands import ports as cmd_ports
    from ydbctl.commands import regions as cmd_regions
    from ydbctl.commands import status as cmd_status
    from ydbctl.commands import version as cmd_version
    from ydbctl.commands import which as cmd_which

    p = _sub("status", help="Composite container + version + ipc + ports")
    p.set_defaults(func=lambda a, prof: cmd_status.run(prof))

    p = _sub("version", help="YottaDB engine + image version info")
    p.set_defaults(func=lambda a, prof: cmd_version.run(prof))

    p = _sub("ports", help="Optional service-port reachability table")
    p.set_defaults(func=lambda a, prof: cmd_ports.run(prof))

    p = _sub("env", help="Show ydb_*/gtm* env vars from inside the container")
    p.add_argument("name", nargs="?", default=None, help="Single var to show")
    p.set_defaults(func=lambda a, prof: cmd_env.run(prof, name=a.name))

    p = _sub("regions", help="List M regions via `gde show`")
    p.set_defaults(func=lambda a, prof: cmd_regions.run(prof))

    p = _sub("files", help="Enumerate .gld / .dat / .mjl / .repl files")
    p.set_defaults(func=lambda a, prof: cmd_files.run(prof))

    p = _sub("dbinfo", help="mupip dumpfhead summary for a region/file")
    p.add_argument("region", nargs="?", default=None,
                   help="Region name (default: DEFAULT)")
    p.add_argument("--file", default=None, help="Override DAT path")
    p.add_argument("--full", action="store_true",
                   help="Include the full record dump")
    p.set_defaults(func=lambda a, prof: cmd_dbinfo.run(
        prof, region=a.region, file=a.file, full=a.full))

    p = _sub("ipc", help="Show shared-memory + semaphore state inside container")
    p.set_defaults(func=lambda a, prof: cmd_ipc.run(prof))

    p = _sub("logs", help="Tail recent journal records")
    p.add_argument("--tail", type=int, default=50,
                   help="Number of lines (default 50)")
    p.set_defaults(func=lambda a, prof: cmd_logs.run(prof, tail=a.tail))

    p = _sub("health", help="Green/yellow verdict with check breakdown")
    p.set_defaults(func=lambda a, prof: cmd_health.run(prof))

    p = _sub("which", help="Explain the underlying mechanism for an op")
    p.add_argument("op", nargs="?", default=None,
                   help="Operation name (omit to list all)")
    p.set_defaults(func=lambda a, prof: cmd_which.run(prof, op=a.op))

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    if argcomplete is not None:
        argcomplete.autocomplete(parser)
    args = parser.parse_args(argv)
    args.profile = getattr(args, "profile", None)
    args.human = getattr(args, "human", False)
    args.pretty = getattr(args, "pretty", False)
    try:
        profile = load_profile(profile=args.profile)
    except KeyError as e:
        env = error_envelope(args.command or "ydbctl",
                              code=ErrorCode.USAGE, message=str(e))
        return _emit(env, args=args)

    try:
        envelope = args.func(args, profile)
    except Exception as e:  # pragma: no cover
        log.exception("internal error")
        envelope = error_envelope(
            args.command or "ydbctl",
            code=ErrorCode.INTERNAL,
            message=f"{type(e).__name__}: {e}",
        )
    return _emit(envelope, args=args)


if __name__ == "__main__":
    sys.exit(main())
