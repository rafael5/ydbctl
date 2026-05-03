"""`ydbctl health` — green / yellow / red verdict with check breakdown."""

from __future__ import annotations

from typing import Any

from ydbctl.commands import ipc as cmd_ipc
from ydbctl.commands import status as cmd_status
from ydbctl.config import Profile
from ydbctl.output import success_envelope


def run(profile: Profile) -> dict[str, Any]:
    status_env = cmd_status.run(profile)
    if not status_env["ok"]:
        return {**status_env, "command": "health"}

    ipc_env = cmd_ipc.run(profile)

    checks: list[dict[str, Any]] = [
        _check("container_running", status_env["data"]["container"]["running"]),
        _check("ydb_version_resolves", bool(status_env["data"].get("ydb_release"))),
        _check("ipc_probe_ok", ipc_env["ok"]),
    ]
    if ipc_env["ok"]:
        orphans = [s for s in ipc_env["data"]["shared_memory"]
                   if s.get("nattch", 0) == 0]
        checks.append(_check(
            "no_ipc_orphans",
            len(orphans) == 0,
            note=f"{len(orphans)} segment(s) with nattch=0",
        ))

    failures = [c for c in checks if not c["ok"]]
    verdict = "green" if not failures else "yellow"

    return success_envelope("health", {
        "verdict": verdict,
        "checks": checks,
        "failures": [c["name"] for c in failures],
    })


def _check(name: str, ok: bool, *, note: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"name": name, "ok": bool(ok)}
    if note is not None:
        out["note"] = note
    return out
