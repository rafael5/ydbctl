"""Unit tests for the config / profile module."""

from __future__ import annotations

from pathlib import Path

import pytest

from ydbctl.config import load_profile


def _empty(tmp_path: Path) -> Path:
    return tmp_path / "missing.toml"


class TestDefaults:
    def test_default_container(self, tmp_path, monkeypatch):
        for k in ("YDBCTL_PROFILE", "YDBCTL_CONTAINER", "YDBCTL_HOST",
                  "YDBCTL_DATA_DIR", "YDBCTL_YDB_DIST"):
            monkeypatch.delenv(k, raising=False)
        prof = load_profile(config_path=_empty(tmp_path))
        assert prof.container == "ydb-test"
        assert prof.host == "127.0.0.1"
        assert prof.ydb_dist == "/opt/yottadb/current"
        assert prof.gui_port == 9080
        assert prof.rocto_port == 1337


class TestEnvOverrides:
    def test_override_container(self, tmp_path, monkeypatch):
        monkeypatch.setenv("YDBCTL_CONTAINER", "ydb-prod")
        prof = load_profile(config_path=_empty(tmp_path))
        assert prof.container == "ydb-prod"

    def test_override_data_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv("YDBCTL_DATA_DIR", "/srv/ydb")
        prof = load_profile(config_path=_empty(tmp_path))
        assert prof.data_dir == Path("/srv/ydb")

    def test_override_ydb_dist(self, tmp_path, monkeypatch):
        monkeypatch.setenv("YDBCTL_YDB_DIST", "/usr/local/lib/yottadb/r202")
        prof = load_profile(config_path=_empty(tmp_path))
        assert prof.ydb_dist == "/usr/local/lib/yottadb/r202"


class TestTomlProfile:
    def test_loads_default_profile(self, tmp_path, monkeypatch):
        monkeypatch.delenv("YDBCTL_PROFILE", raising=False)
        cfg = tmp_path / "c.toml"
        cfg.write_text("""
default_profile = "p1"
[profiles.p1]
container = "alpha"
host = "10.0.0.1"
ydb_dist = "/opt/ydb/r2.05"
vista = true
""", encoding="utf-8")
        prof = load_profile(config_path=cfg)
        assert prof.container == "alpha"
        assert prof.host == "10.0.0.1"
        assert prof.vista is True

    def test_unknown_profile_raises(self, tmp_path):
        cfg = tmp_path / "c.toml"
        cfg.write_text("""
default_profile = "p1"
[profiles.p1]
container = "x"
""", encoding="utf-8")
        with pytest.raises(KeyError):
            load_profile(profile="missing", config_path=cfg)


class TestProfileMethods:
    def test_data_dir_expands_user(self, tmp_path, monkeypatch):
        monkeypatch.setenv("YDBCTL_DATA_DIR", "~/data/test")
        prof = load_profile(config_path=_empty(tmp_path))
        assert "~" not in str(prof.data_dir)
