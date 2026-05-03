"""End-to-end CLI tests — every Phase 1 subcommand via subprocess.

Each test invokes the CLI like a user would: `python -m ydbctl <cmd>`,
parses the JSON envelope, and asserts on the shape against the live
`ydb-test` container.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"


def _cli(*args: str, expect_returncode: int = 0) -> dict:
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    res = subprocess.run(
        [sys.executable, "-m", "ydbctl", *args],
        capture_output=True, text=True, env=env, timeout=60,
    )
    assert res.returncode == expect_returncode, (
        f"rc={res.returncode}, expected {expect_returncode}\n"
        f"stdout: {res.stdout}\nstderr: {res.stderr}"
    )
    return json.loads(res.stdout)


@pytest.mark.integration
class TestEndToEnd:
    def test_version(self, live_ydb):
        env = _cli("version")
        assert env["ok"] is True
        assert env["data"]["ydb_release"].startswith("r2.")
        assert "Linux" in env["data"]["platform"]
        assert env["data"]["build_type"] == "Production"

    def test_ports(self, live_ydb):
        env = _cli("ports")
        assert env["ok"] is True
        rows = env["data"]
        roles = {r["role"] for r in rows}
        # All four optional listeners are listed (most unreachable by default)
        assert {"ydb_gui", "ydb_gui_stats", "rocto", "gtcm"} <= roles

    def test_env(self, live_ydb):
        env = _cli("env")
        assert env["ok"] is True
        vars_ = env["data"]["vars"]
        assert "ydb_dist" in vars_
        assert vars_["ydb_dir"].startswith("/data")

    def test_env_specific(self, live_ydb):
        env = _cli("env", "ydb_dir")
        assert env["ok"] is True
        assert env["data"]["name"] == "ydb_dir"

    def test_env_missing_returns_not_found(self, live_ydb):
        proc = subprocess.run(
            [sys.executable, "-m", "ydbctl", "env", "definitely_not_a_var"],
            capture_output=True, text=True,
            env={**os.environ, "PYTHONPATH": str(SRC)},
            timeout=30,
        )
        assert proc.returncode == 6
        env = json.loads(proc.stdout)
        assert env["error"]["code"] == "not_found"

    def test_regions(self, live_ydb):
        env = _cli("regions")
        assert env["ok"] is True
        # The default ydb_env_set install creates DEFAULT, YDBAIM, YDBOCTO, YDBJNLF
        regions = set(env["data"]["regions"])
        assert "DEFAULT" in regions
        # At least one plugin region is present
        assert any(r.startswith("YDB") for r in regions)
        assert env["data"]["count"] >= 1

    def test_files(self, live_ydb):
        env = _cli("files")
        assert env["ok"] is True
        files = env["data"]["files"]
        # At least the default yottadb.dat + yottadb.gld
        kinds = {f["kind"] for f in files}
        assert "database" in kinds
        assert "global_directory" in kinds
        # All paths under /data
        assert all(f["path"].startswith("/data") for f in files)

    def test_dbinfo_default(self, live_ydb):
        env = _cli("dbinfo")
        assert env["ok"] is True
        d = env["data"]
        assert d["block_size_bytes"] == 4096
        assert d["total_blocks"] >= 100
        assert d["access_method"] in ("BG", "MM")

    def test_dbinfo_full(self, live_ydb):
        env = _cli("dbinfo", "--full")
        assert env["ok"] is True
        # Full record dump exposes all sgmnt_data.* fields
        assert "full" in env["data"]
        assert len(env["data"]["full"]) > 50

    def test_dbinfo_missing_file(self, live_ydb):
        proc = subprocess.run(
            [sys.executable, "-m", "ydbctl",
             "dbinfo", "--file", "/nonexistent/path.dat"],
            capture_output=True, text=True,
            env={**os.environ, "PYTHONPATH": str(SRC)},
            timeout=30,
        )
        # Either not_found (exit 6) or ydb_error (exit 7) — both acceptable
        assert proc.returncode in (6, 7)

    def test_ipc(self, live_ydb):
        env = _cli("ipc")
        assert env["ok"] is True
        d = env["data"]
        assert "shared_memory" in d
        assert "semaphores" in d

    def test_logs(self, live_ydb):
        env = _cli("logs", "--tail", "5")
        assert env["ok"] is True
        # Either lines were produced or "no journal file" message
        assert "lines" in env["data"]

    def test_status(self, live_ydb):
        env = _cli("status")
        assert env["ok"] is True
        d = env["data"]
        assert d["container"]["running"] is True
        assert d["ydb_release"].startswith("r2.")

    def test_health(self, live_ydb):
        env = _cli("health")
        assert env["ok"] is True
        assert env["data"]["verdict"] in ("green", "yellow")
        assert isinstance(env["data"]["checks"], list)

    def test_which_no_op(self, live_ydb):
        env = _cli("which")
        assert env["ok"] is True
        ops = env["data"]["operations"]
        names = {r["op"] for r in ops}
        for required in ("status", "version", "ports", "env", "regions",
                         "files", "dbinfo", "ipc", "logs", "health", "which"):
            assert required in names

    def test_which_specific(self, live_ydb):
        env = _cli("which", "dbinfo")
        assert env["ok"] is True
        assert env["data"]["op"] == "dbinfo"
        # Substituted profile values appear in the underlying string
        assert "ydb-test" in env["data"]["underlying"]


# ---- Non-integration: usage / parser / unit ----


class TestUsage:
    def test_no_args_exits_2(self):
        proc = subprocess.run(
            [sys.executable, "-m", "ydbctl"],
            capture_output=True, text=True,
            env={**os.environ, "PYTHONPATH": str(SRC)},
            timeout=10,
        )
        assert proc.returncode == 2

    def test_help_lists_phase_1_and_2_subcommands(self):
        proc = subprocess.run(
            [sys.executable, "-m", "ydbctl", "--help"],
            capture_output=True, text=True,
            env={**os.environ, "PYTHONPATH": str(SRC)},
            timeout=10,
        )
        assert proc.returncode == 0
        # Phase 1
        for known in ("status", "version", "ports", "env", "regions",
                      "files", "dbinfo", "ipc", "logs", "health", "which"):
            assert known in proc.stdout
        # Phase 2
        for known in ("exec", "sql", "shell", "globals"):
            assert known in proc.stdout
        # Phase 3
        for known in ("integ", "reorg", "freeze", "locks",
                      "rundown", "recover", "backup", "restore"):
            assert known in proc.stdout
