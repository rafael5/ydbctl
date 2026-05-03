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
    from pathlib import Path

    from ydbctl.commands import backup as cmd_backup
    from ydbctl.commands import dbinfo as cmd_dbinfo
    from ydbctl.commands import env as cmd_env
    from ydbctl.commands import exec_cmd as cmd_exec
    from ydbctl.commands import files as cmd_files
    from ydbctl.commands import freeze as cmd_freeze
    from ydbctl.commands import globals_cmd as cmd_globals
    from ydbctl.commands import health as cmd_health
    from ydbctl.commands import integ as cmd_integ
    from ydbctl.commands import ipc as cmd_ipc
    from ydbctl.commands import locks as cmd_locks
    from ydbctl.commands import logs as cmd_logs
    from ydbctl.commands import ports as cmd_ports
    from ydbctl.commands import recover as cmd_recover
    from ydbctl.commands import regions as cmd_regions
    from ydbctl.commands import reorg as cmd_reorg
    from ydbctl.commands import restore as cmd_restore
    from ydbctl.commands import rundown as cmd_rundown
    from ydbctl.commands import shell as cmd_shell
    from ydbctl.commands import sql as cmd_sql
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

    # ---- Phase 2: execution ----
    p = _sub("exec", help="Run M code via yottadb -run %%XCMD (or --direct)")
    p.add_argument("code", nargs="?", default=None,
                   help="Inline M code (omit when using --file/--stdin/--run)")
    p.add_argument("--file", type=Path, default=None,
                   help="Read M code from a file")
    p.add_argument("--stdin", action="store_true",
                   help="Read M code from stdin")
    p.add_argument("--run", dest="run_entry", default=None,
                   help="Invoke a labelled entry: ENTRY^ROUTINE")
    p.add_argument("--arg", dest="run_args", action="append", default=None,
                   help="Argument to pass to --run (repeatable)")
    p.add_argument("--direct", action="store_true",
                   help="Use yottadb -direct heredoc (multi-line scripts)")
    p.add_argument("--timeout", type=float, default=60.0)
    p.set_defaults(func=lambda a, prof: cmd_exec.run(
        prof,
        code=a.code,
        stdin_text=sys.stdin.read() if a.stdin else None,
        file=a.file,
        run_entry=a.run_entry,
        run_args=a.run_args,
        direct=a.direct,
        timeout=a.timeout,
    ))

    p = _sub("sql", help="Run SQL via Octo (when installed)")
    p.add_argument("statement", nargs="?", default=None,
                   help="Inline SQL (omit when using --file)")
    p.add_argument("--file", type=Path, default=None,
                   help="Read SQL from a file")
    p.add_argument("--timeout", type=float, default=60.0)
    p.set_defaults(func=lambda a, prof: cmd_sql.run(
        prof, statement=a.statement, file=a.file, timeout=a.timeout))

    p = _sub("shell", help="Open an interactive yottadb -direct session")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the docker-exec argv instead of execing")
    p.set_defaults(func=lambda a, prof: cmd_shell.run(prof, dry_run=a.dry_run))

    p_glob = _sub("globals", help="ZWRITE / mupip extract globals")
    glob_sub = p_glob.add_subparsers(dest="globals_sub", required=False,
                                      metavar="ACTION")

    p_show = glob_sub.add_parser("show", parents=[globals_parent],
                                  help="Dump a global subtree (ZWRITE)")
    p_show.add_argument("name", help="Global name (with or without leading ^)")
    p_show.set_defaults(globals_sub="show")

    p_export = glob_sub.add_parser(
        "export", parents=[globals_parent],
        help="Extract a global to a host file (mupip extract)",
    )
    p_export.add_argument("name", help="Global name (with or without leading ^)")
    p_export.add_argument("--to", type=Path, default=None,
                          help="Host output path (default: cwd/<name>.zwr)")
    p_export.add_argument("--format", default="ZWR",
                          help="Output format: ZWR (default), GO, BINARY")
    p_export.set_defaults(globals_sub="export")

    p_glob.set_defaults(func=lambda a, prof: cmd_globals.dispatch(a, prof))

    # ---- Phase 3: maintenance ----
    p = _sub("integ", help="mupip integ — integrity check")
    p.add_argument("--region", default="*",
                   help="Region (default: * = all regions)")
    p.add_argument("--full", action="store_true",
                   help="Run -full integ instead of -fast")
    p.set_defaults(func=lambda a, prof: cmd_integ.run(
        prof, region=a.region, full=a.full))

    p = _sub("reorg", help="mupip reorg — defrag/coalesce blocks")
    p.add_argument("--region", default="*",
                   help="Region (default: * = all regions)")
    p.add_argument("--truncate", action="store_true",
                   help="Truncate to free unused blocks")
    p.set_defaults(func=lambda a, prof: cmd_reorg.run(
        prof, region=a.region, truncate=a.truncate))

    p = _sub("freeze", help="mupip freeze — suspend/resume DB updates")
    p.add_argument("--region", default="*",
                   help="Region (default: * = all regions)")
    grp = p.add_mutually_exclusive_group(required=False)
    grp.add_argument("--on", action="store_true", help="Freeze the region")
    grp.add_argument("--off", action="store_true", help="Unfreeze the region")
    p.set_defaults(func=lambda a, prof: cmd_freeze.run(
        prof, on=a.on, off=a.off, region=a.region))

    p = _sub("rundown", help="mupip rundown — release orphan IPC")
    p.add_argument("--region", default="*",
                   help="Region (default: * = all regions)")
    p.set_defaults(func=lambda a, prof: cmd_rundown.run(prof, region=a.region))

    p = _sub("recover", help="mupip journal -recover — replay journal records")
    p.add_argument("--region", default="*",
                   help="Region (default: * = all regions)")
    p.add_argument("--journal-file", default=None,
                   help="Specific journal file to recover (overrides --region)")
    p.add_argument("--forward", action="store_true",
                   help="Forward recovery (default: backward)")
    p.set_defaults(func=lambda a, prof: cmd_recover.run(
        prof, region=a.region, journal_file=a.journal_file,
        backward=not a.forward))

    p = _sub("backup", help="mupip backup -bytestream — write backup tarball")
    p.add_argument("region", nargs="?", default="DEFAULT",
                   help="Region to back up (default: DEFAULT)")
    p.add_argument("--to", type=Path, default=None,
                   help="Host output dir (default: ~/data/backups/ydb-test-<UTC>)")
    p.add_argument("--offline", action="store_true",
                   help="Take an offline (frozen) backup (slower, more consistent)")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=lambda a, prof: cmd_backup.run(
        prof, region=a.region, to=a.to, online=not a.offline,
        dry_run=a.dry_run))

    p = _sub("restore",
             help="mupip restore — overwrite DAT from backup (destructive)")
    p.add_argument("--from", dest="source", type=Path, required=True,
                   help="Backup bytestream file to restore from")
    p.add_argument("--target", required=True,
                   help="In-container target DAT path")
    p.add_argument("--yes", action="store_true",
                   help="Confirm; required to actually overwrite")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=lambda a, prof: cmd_restore.run(
        prof, source=a.source, target_dat=a.target,
        yes=a.yes, dry_run=a.dry_run))

    p_locks = _sub("locks", help="lke show / clear active M LOCKs")
    locks_sub = p_locks.add_subparsers(dest="locks_sub", required=False,
                                        metavar="ACTION")

    p_lshow = locks_sub.add_parser("show", parents=[globals_parent],
                                    help="Show active locks (lke show -all)")
    p_lshow.add_argument("--region", default="*")
    p_lshow.set_defaults(locks_sub="show")

    p_lclr = locks_sub.add_parser(
        "clear", parents=[globals_parent],
        help="Clear locks (mutating; --yes to confirm)",
    )
    p_lclr.add_argument("--region", default="*")
    p_lclr.add_argument("--yes", action="store_true")
    p_lclr.add_argument("--dry-run", action="store_true")
    p_lclr.set_defaults(locks_sub="clear")

    p_locks.set_defaults(func=lambda a, prof: cmd_locks.dispatch(a, prof))

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
