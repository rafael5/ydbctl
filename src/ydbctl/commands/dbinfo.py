"""`ydbctl dbinfo [REGION|--file PATH]` — mupip dumpfhead summary."""

from __future__ import annotations

from typing import Any

from ydbctl.config import Profile
from ydbctl.output import ErrorCode, error_envelope, success_envelope
from ydbctl.parsers.dumpfhead import dumpfhead_summary, parse_dumpfhead
from ydbctl.ydb_exec import YdbError, mupip, ydb_run


def run(
    profile: Profile,
    *,
    region: str | None = None,
    file: str | None = None,
    full: bool = False,
) -> dict[str, Any]:
    """Inspect a database file via `mupip dumpfhead`.

    If `region` is given, resolve it through GDE → DAT path. If `file`
    is given, use it directly. Otherwise default to the active default
    region (yottadb.dat).
    """
    if file is not None:
        target = file
    elif region is not None:
        # For Phase 1, use the conventional path; full GDE-resolved
        # path is a Phase 1.5 enrichment.
        target = _conventional_dat_path(profile, region)
    else:
        target = "$ydb_gbldir"
        # $ydb_gbldir points at the .gld; the default DAT lives next to it.
        # Resolve via shell expansion.
        try:
            res = ydb_run(profile, "echo $ydb_dir/$ydb_rel/g/yottadb.dat")
            target = res["stdout"].strip()
        except YdbError as e:
            return error_envelope("dbinfo", code=ErrorCode.YDB_ERROR,
                                   message=str(e))

    try:
        text = mupip(profile, ["dumpfhead", "-file", target])
    except YdbError as e:
        msg = str(e)
        if "FILENOTFND" in msg or "No such file" in msg or "not found" in msg:
            return error_envelope(
                "dbinfo", code=ErrorCode.NOT_FOUND,
                message=f"DAT not found: {target}",
            )
        return error_envelope("dbinfo", code=ErrorCode.YDB_ERROR, message=msg)

    raw = parse_dumpfhead(text)
    summary = dumpfhead_summary(raw)
    summary["file"] = target
    if full:
        summary["full"] = raw

    return success_envelope("dbinfo", summary)


def _conventional_dat_path(profile: Profile, region: str) -> str:
    """The default ydb_env_set layout puts every region's DAT under
    $ydb_dir/$ydb_rel/g/. The DEFAULT region uses yottadb.dat.
    """
    name = "yottadb.dat" if region.upper() == "DEFAULT" else f"{region.lower()}.dat"
    # Caller's ydb_run will expand $ydb_dir / $ydb_rel
    return f"$ydb_dir/$ydb_rel/g/{name}"
