"""YottaDB-aware `docker exec` wrapper.

Every YDB binary (mupip, gde, lke, yottadb) needs the `ydb_*` env vars
set, which `$ydb_dist/ydb_env_set` configures. We always source it
inside `bash -c` before running the actual binary.

The wrapper is the single place that knows about ydb_env_set sourcing
— all command modules go through `ydb_run()`.
"""

from __future__ import annotations

import re
import subprocess
from typing import Any

from ydbctl.config import Profile


class YdbError(Exception):
    """A `ydb_run` invocation failed (non-zero exit, missing binary, timeout)."""


_QUIT_RE = re.compile(r"^\s*(?:QUIT|Q)\b\s*$", re.IGNORECASE | re.MULTILINE)
_YDB_ERROR_RE = re.compile(r"%(?:YDB|GTM)-[EFW]-[A-Z][A-Z0-9_]*")


def ensure_halt(script: str) -> str:
    """Make sure an M script ends with HALT; replace trailing QUIT/Q.

    Tolerates trailing comments + whitespace.
    """
    lines = script.splitlines()
    last_idx = -1
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip():
            last_idx = i
            break
    if last_idx < 0:
        return script + "\nHALT\n"
    last = lines[last_idx].strip().upper()
    if last in ("HALT", "H"):
        return script.rstrip() + "\n"
    if _QUIT_RE.match(lines[last_idx]):
        lines[last_idx] = "HALT"
        return "\n".join(lines) + "\n"
    return script.rstrip() + "\nHALT\n"


def _has_ydb_error(text: str) -> bool:
    return bool(_YDB_ERROR_RE.search(text))


def _extract_ydb_error(text: str) -> str:
    m = _YDB_ERROR_RE.search(text)
    if not m:
        return text.strip()[:400]
    for line in text.splitlines():
        if m.group(0) in line:
            return line.strip()
    return m.group(0)


def _strip_ydb_prompts(text: str) -> str:
    """Remove `YDB>` prompt lines from `yottadb -direct` output."""
    out_lines: list[str] = []
    for line in text.splitlines():
        if line.strip() == "YDB>" or line.rstrip().endswith("YDB>"):
            stripped = line.replace("YDB>", "").rstrip()
            if stripped:
                out_lines.append(stripped)
            continue
        out_lines.append(line)
    return "\n".join(out_lines)


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


def yottadb_xcmd(
    profile: Profile,
    code: str,
    *,
    timeout: float = 60.0,
) -> str:
    """Execute one-shot M code via `yottadb -run %XCMD '<code>'`.

    %XCMD is the YottaDB built-in for "compile and run this string of
    M commands". Newlines in `code` are flattened to spaces.
    """
    flat = " ".join(code.split())
    res = ydb_run(profile, f"yottadb -run %XCMD {_shell_quote(flat)}",
                  timeout=timeout)
    if res["returncode"] != 0 or _has_ydb_error(res["stdout"] + res["stderr"]):
        msg = _extract_ydb_error(res["stderr"] + res["stdout"])
        raise YdbError(f"%XCMD: {msg}")
    return res["stdout"]


def yottadb_direct(
    profile: Profile,
    script: str,
    *,
    timeout: float = 60.0,
) -> str:
    """Multi-line M script via `yottadb -direct` heredoc.

    Auto-appends HALT, strips YDB> prompts so callers see clean output.
    """
    payload = ensure_halt(script)
    res = ydb_run(profile, "yottadb -direct",
                  input_text=payload, timeout=timeout)
    if res["returncode"] != 0:
        raise YdbError(
            f"yottadb -direct exit {res['returncode']}: "
            f"{(res['stderr'] or res['stdout']).strip()[:400]}"
        )
    if _has_ydb_error(res["stdout"] + res["stderr"]):
        raise YdbError(_extract_ydb_error(res["stdout"] + res["stderr"]))
    return _strip_ydb_prompts(res["stdout"])


def yottadb_run_entry(
    profile: Profile,
    entry: str,
    *args: str,
    timeout: float = 60.0,
) -> str:
    """Run `yottadb -run <entry> <args...>` (entry is "LABEL^ROUTINE")."""
    quoted = " ".join(_shell_quote(a) for a in args)
    cmd = f"yottadb -run {_shell_quote(entry)}"
    if quoted:
        cmd += f" {quoted}"
    res = ydb_run(profile, cmd, timeout=timeout)
    if res["returncode"] != 0 or _has_ydb_error(res["stdout"] + res["stderr"]):
        msg = _extract_ydb_error(res["stderr"] + res["stdout"])
        raise YdbError(f"yottadb -run {entry}: {msg}")
    return res["stdout"]


def has_octo(profile: Profile) -> bool:
    octo_path = f"{profile.ydb_dist}/plugin/bin/octo"
    res = ydb_run(profile, f"test -x {octo_path} && echo OK || echo MISSING",
                  timeout=5.0)
    return "OK" in res["stdout"]


def octo_exec(
    profile: Profile,
    sql: str,
    *,
    timeout: float = 60.0,
) -> str:
    """Run a SQL statement through Octo. Raises if Octo not installed."""
    octo_path = f"{profile.ydb_dist}/plugin/bin/octo"
    if not has_octo(profile):
        raise YdbError(
            "Octo CLI not installed in this container. The base image "
            "ships without Octo; switch to yottadb/yottadb-debian or run "
            f"`ydbinstall --octo` to add it. Expected: {octo_path}"
        )
    flat = " ".join(sql.split())
    res = ydb_run(profile, f"echo {_shell_quote(flat)} | {octo_path}",
                  timeout=timeout)
    if res["returncode"] != 0 or _has_ydb_error(res["stdout"] + res["stderr"]):
        msg = _extract_ydb_error(res["stderr"] + res["stdout"])
        raise YdbError(f"octo: {msg}")
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
