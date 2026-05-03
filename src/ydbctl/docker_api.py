"""Docker CLI wrapper for ydbctl.

Wraps `docker inspect` / `docker ps` / `docker exec` for ydb-test.
Mirrors irisctl/docker_api.py.
"""

from __future__ import annotations

import json
import socket
import subprocess
import time
from typing import Any


class DockerError(Exception):
    """docker CLI failed or returned no result for the given container."""


def _run(cmd: list[str], timeout: float = 15.0) -> str:
    try:
        res = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired as e:
        raise DockerError(f"timeout: {' '.join(cmd)}") from e
    except FileNotFoundError as e:
        raise DockerError("docker CLI not found on PATH") from e
    if res.returncode != 0:
        raise DockerError(
            f"{' '.join(cmd)}: exit {res.returncode}: "
            f"{res.stderr.strip() or res.stdout.strip()}"
        )
    return res.stdout


def container_exists(name: str) -> bool:
    out = _run([
        "docker", "ps", "-a", "--filter", f"name=^{name}$",
        "--format", "{{.Names}}",
    ])
    return name in out.split()


def inspect_container(name: str) -> dict[str, Any]:
    out = _run(["docker", "inspect", name])
    try:
        data = json.loads(out)
    except json.JSONDecodeError as e:
        raise DockerError(f"invalid JSON from docker inspect: {e}") from e
    if not data:
        raise DockerError(f"no inspect data for {name!r}")
    return data[0]


def container_state(name: str) -> dict[str, Any]:
    info = inspect_container(name)
    state = info.get("State", {})
    return {
        "status": state.get("Status", "unknown"),
        "running": bool(state.get("Running", False)),
        "started_at": state.get("StartedAt", ""),
        "exit_code": state.get("ExitCode"),
    }


def image_labels(name: str) -> dict[str, str]:
    info = inspect_container(name)
    return dict(info.get("Config", {}).get("Labels") or {})


def list_published_ports(name: str) -> list[dict[str, Any]]:
    info = inspect_container(name)
    out: list[dict[str, Any]] = []
    bindings = info.get("NetworkSettings", {}).get("Ports") or {}
    for cport, host_list in bindings.items():
        try:
            port_str, proto = cport.split("/", 1)
            cport_num = int(port_str)
        except ValueError:
            continue
        if not host_list:
            out.append({"container_port": cport_num, "host_port": None,
                        "proto": proto})
            continue
        seen_hosts: set[int] = set()
        for binding in host_list:
            hp = binding.get("HostPort")
            if hp is None:
                continue
            try:
                hp_num = int(hp)
            except (TypeError, ValueError):
                continue
            if hp_num in seen_hosts:
                continue
            seen_hosts.add(hp_num)
            out.append({"container_port": cport_num, "host_port": hp_num,
                        "proto": proto})
    return out


def docker_exec(
    name: str,
    args: list[str],
    *,
    input_text: str | None = None,
    timeout: float = 60.0,
) -> str:
    """Run `docker exec [-i] <name> <args...>` and return stdout."""
    cmd = ["docker", "exec"]
    if input_text is not None:
        cmd.append("-i")
    cmd.extend([name, *args])
    try:
        res = subprocess.run(
            cmd, input=input_text, capture_output=True, text=True,
            timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise DockerError(f"docker exec timeout: {' '.join(cmd[:5])}") from e
    if res.returncode != 0:
        raise DockerError(
            f"docker exec exit {res.returncode}: "
            f"{(res.stderr.strip() or res.stdout.strip())[:400]}"
        )
    return res.stdout


def cat_file_via_helper(host_path: str) -> str:
    """Read an entire file via a transient root-uid alpine container."""
    cmd = [
        "docker", "run", "--rm", "--user", "0",
        "-v", f"{host_path}:{host_path}:ro",
        "alpine", "cat", host_path,
    ]
    return _run(cmd, timeout=30)


def wait_for_tcp(
    host: str, ports: list[int], *,
    timeout: float = 30.0, interval: float = 0.5,
) -> dict[int, bool]:
    deadline = time.monotonic() + timeout
    state: dict[int, bool] = {p: False for p in ports}
    while time.monotonic() < deadline:
        for p in ports:
            if state[p]:
                continue
            try:
                with socket.create_connection((host, p), timeout=1.0):
                    state[p] = True
            except OSError:
                pass
        if all(state.values()):
            return state
        time.sleep(interval)
    return state


def tcp_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def cp_to_container(src_path: str, container: str, dest_path: str) -> None:
    """`docker cp <src> <container>:<dest>`."""
    _run(["docker", "cp", src_path, f"{container}:{dest_path}"], timeout=120)


def cp_from_container(container: str, src_path: str, dest_path: str) -> None:
    """`docker cp <container>:<src> <dest>`."""
    _run(["docker", "cp", f"{container}:{src_path}", dest_path], timeout=120)
