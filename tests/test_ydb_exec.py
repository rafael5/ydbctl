"""Tests for ydb_exec — `docker exec` wrapper that sources ydb_env_set."""

from __future__ import annotations

import pytest

from ydbctl.config import load_profile
from ydbctl.ydb_exec import (
    YdbError,
    env_dump,
    gde_show,
    mupip,
    ydb_run,
    yottadb_version,
)


def _profile(tmp_path):
    return load_profile(config_path=tmp_path / "missing.toml")


@pytest.mark.integration
class TestYdbRun:
    def test_basic_command(self, live_ydb, tmp_path):
        prof = _profile(tmp_path)
        res = ydb_run(prof, "echo hello")
        assert res["returncode"] == 0
        assert "hello" in res["stdout"]

    def test_env_set_sourced(self, live_ydb, tmp_path):
        prof = _profile(tmp_path)
        res = ydb_run(prof, "echo $ydb_dist")
        assert "/opt/yottadb" in res["stdout"]

    def test_failing_command_returns_nonzero(self, live_ydb, tmp_path):
        prof = _profile(tmp_path)
        res = ydb_run(prof, "false")
        assert res["returncode"] != 0


@pytest.mark.integration
class TestYottadbVersion:
    def test_returns_version_string(self, live_ydb, tmp_path):
        out = yottadb_version(_profile(tmp_path))
        assert "YottaDB release:" in out
        assert "r2." in out


@pytest.mark.integration
class TestEnvDump:
    def test_returns_dict_of_env_vars(self, live_ydb, tmp_path):
        env = env_dump(_profile(tmp_path))
        assert "ydb_dist" in env
        assert "ydb_dir" in env
        assert "ydb_gbldir" in env
        assert env["ydb_dir"].startswith("/data")


@pytest.mark.integration
class TestMupip:
    def test_dumpfhead(self, live_ydb, tmp_path):
        out = mupip(_profile(tmp_path), ["dumpfhead", "-file",
                                          "/data/r2.07_x86_64/g/yottadb.dat"])
        assert 'sgmnt_data.blk_size' in out


@pytest.mark.integration
class TestGdeShow:
    def test_returns_show_output(self, live_ydb, tmp_path):
        out = gde_show(_profile(tmp_path))
        # The default region should appear
        assert "TEMPLATES" in out or "Region" in out


class TestErrors:
    def test_missing_container_raises(self, tmp_path, monkeypatch):
        monkeypatch.setenv("YDBCTL_CONTAINER", "definitely-not-real-xyz")
        prof = _profile(tmp_path)
        with pytest.raises(YdbError):
            yottadb_version(prof, timeout=5.0)
