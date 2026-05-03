"""YottaDB-aware `docker exec` wrapper.

Every YDB binary (mupip, gde, lke, yottadb) needs the `ydb_*` env vars
set, which `$ydb_dist/ydb_env_set` configures. We always source it
inside `bash -c` before running the actual binary.

The wrapper is the single place that knows about ydb_env_set sourcing
— all command modules go through `ydb_run()`.
"""

from __future__ import annotations

import subprocess
from typing import Any

from ydbctl.config import Profile


class YdbError(Exception):
    """A `ydb_run` invocation failed (non-zero exit, missing binary, timeout)."""


def ydb_run(
    profile: Profile,
    cmd: str,
    *,
    input_text: str | None = None,
    timeout: float = 60.0,
) -> dict[str, Any]:
    """Run `cmd` inside the container with ydb_env_set sourced.

    Returns {stdout, stderr, returncode}.
    Raises YdbError on docker / subprocess errors (not on YDB-internal
    non-zero exits — caller decides how to interpret those).
    """
    full = f". {profile.ydb_dist}/ydb_env_set >/dev/null 2>&1 ; {cmd}"
    docker_cmd = ["docker", "exec"]
    if input_text is not None:
        docker_cmd.append("-i")
    docker_cmd.extend([profile.container, "bash", "-c", full])

    try:
        res = subprocess.run(
            docker_cmd,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise YdbError(f"timeout after {timeout}s") from e
    except FileNotFoundError as e:
        raise YdbError("docker CLI not found on PATH") from e

    return {
        "stdout": res.stdout or "",
        "stderr": res.stderr or "",
        "returncode": res.returncode,
    }


def gde_show(profile: Profile, *, timeout: float = 30.0) -> str:
    """Run `gde` with `show` then `exit` on stdin; return stdout."""
    res = ydb_run(profile, "mumps -run GDE",
                  input_text="show\nexit\n", timeout=timeout)
    if res["returncode"] != 0:
        raise YdbError(
            f"gde show exit {res['returncode']}: {res['stderr'][:300]}"
        )
    return res["stdout"]


def mupip(profile: Profile, args: list[str], *, timeout: float = 60.0) -> str:
    """Run `mupip <args...>`; return stdout."""
    quoted = " ".join(_shell_quote(a) for a in args)
    res = ydb_run(profile, f"mupip {quoted}", timeout=timeout)
    if res["returncode"] != 0:
        # mupip prints errors to stderr; surface both
        raise YdbError(
            f"mupip {quoted}: exit {res['returncode']}: "
            f"{(res['stderr'] or res['stdout'])[:400]}"
        )
    return res["stdout"]


def lke(profile: Profile, args: list[str], *, timeout: float = 30.0) -> str:
    """Run `lke <args...>`; return stdout."""
    cmd = "show -all" if args == ["show"] else " ".join(args)
    res = ydb_run(profile, "lke", input_text=f"{cmd}\nexit\n", timeout=timeout)
    if res["returncode"] != 0:
        raise YdbError(f"lke {cmd}: exit {res['returncode']}: "
                        f"{res['stderr'][:300]}")
    return res["stdout"]


def yottadb_version(profile: Profile, *, timeout: float = 10.0) -> str:
    res = ydb_run(profile, "yottadb -version", timeout=timeout)
    if res["returncode"] != 0:
        raise YdbError(f"yottadb -version exit {res['returncode']}")
    return res["stdout"]


def env_dump(profile: Profile, *, timeout: float = 10.0) -> dict[str, str]:
    """Source ydb_env_set + emit `ydb_*` and `gtm*` env vars."""
    res = ydb_run(profile, 'env | grep -E "^(ydb_|gtm)"', timeout=timeout)
    if res["returncode"] != 0:
        return {}
    out: dict[str, str] = {}
    for line in res["stdout"].splitlines():
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k] = v
    return out


def _shell_quote(s: str) -> str:
    if not s:
        return "''"
    safe = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_./="
    if all(c in safe for c in s):
        return s
    return "'" + s.replace("'", "'\\''") + "'"
