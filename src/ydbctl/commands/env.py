"""`ydbctl env [NAME]` — show ydb_*/gtm* env vars from inside the container."""

from __future__ import annotations

from typing import Any

from ydbctl.config import Profile
from ydbctl.output import ErrorCode, error_envelope, success_envelope
from ydbctl.ydb_exec import YdbError, env_dump


def run(profile: Profile, *, name: str | None = None) -> dict[str, Any]:
    try:
        env = env_dump(profile)
    except YdbError as e:
        return error_envelope("env", code=ErrorCode.YDB_ERROR, message=str(e))

    if name is not None:
        if name not in env:
            return error_envelope(
                "env", code=ErrorCode.NOT_FOUND,
                message=f"variable {name!r} not set in container",
                hint="run `ydbctl env` (no arg) to see all",
            )
        return success_envelope("env", {"name": name, "value": env[name]})

    return success_envelope("env", {
        "container": profile.container,
        "vars": env,
        "count": len(env),
    })
