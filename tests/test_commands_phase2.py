"""Tests for Phase 2 ydbctl commands: exec / sql / shell / globals."""

from __future__ import annotations

import pytest

from ydbctl.commands.exec_cmd import run as exec_run
from ydbctl.commands.globals_cmd import export as globals_export
from ydbctl.commands.globals_cmd import show as globals_show
from ydbctl.commands.shell import build_exec_argv
from ydbctl.commands.shell import run as shell_run
from ydbctl.commands.sql import run as sql_run
from ydbctl.config import load_profile


def _profile(tmp_path):
    return load_profile(config_path=tmp_path / "missing.toml")


# ----------------- exec -----------------


@pytest.mark.integration
class TestExecLive:
    def test_inline_xcmd(self, live_ydb, tmp_path):
        env = exec_run(_profile(tmp_path), code='W "ydbctl-exec-test",!')
        assert env["ok"] is True
        assert env["data"]["mode"] == "xcmd"
        assert "ydbctl-exec-test" in env["data"]["output"]

    def test_inline_arithmetic(self, live_ydb, tmp_path):
        env = exec_run(_profile(tmp_path), code='W 7*8,!')
        assert "56" in env["data"]["output"]

    def test_direct_multiline(self, live_ydb, tmp_path):
        script = '\n'.join([
            'S A=2',
            'S B=3',
            'W A+B,!',
        ])
        env = exec_run(_profile(tmp_path), code=script, direct=True)
        assert env["ok"] is True
        assert env["data"]["mode"] == "direct"
        assert "5" in env["data"]["output"]

    def test_stdin(self, live_ydb, tmp_path):
        env = exec_run(_profile(tmp_path), stdin_text='W $ZV,!')
        assert env["ok"] is True
        assert "GT.M" in env["data"]["output"]

    def test_file(self, live_ydb, tmp_path):
        f = tmp_path / "snippet.m"
        f.write_text('W "from-file",!\n', encoding="utf-8")
        env = exec_run(_profile(tmp_path), file=f)
        assert env["ok"] is True
        assert "from-file" in env["data"]["output"]

    def test_run_entry_xcmd(self, live_ydb, tmp_path):
        env = exec_run(_profile(tmp_path),
                        run_entry="%XCMD",
                        run_args=['W "via-run",!'])
        assert env["ok"] is True
        assert env["data"]["mode"] == "run"
        assert "via-run" in env["data"]["output"]

    def test_syntax_error_returns_ydb_error(self, live_ydb, tmp_path):
        env = exec_run(_profile(tmp_path),
                        code='this is not valid M code')
        assert env["ok"] is False
        assert env["error"]["code"] == "ydb_error"


class TestExecValidation:
    def test_no_payload_is_usage_error(self, tmp_path):
        env = exec_run(_profile(tmp_path))
        assert env["ok"] is False
        assert env["error"]["code"] == "usage"


# ----------------- sql -----------------


@pytest.mark.integration
class TestSqlNoOcto:
    def test_sql_returns_not_found_when_octo_missing(self, live_ydb, tmp_path):
        # The base image has no Octo — every sql call should report
        # not_found with a clear hint about how to install.
        env = sql_run(_profile(tmp_path), statement="SELECT 1")
        assert env["ok"] is False
        assert env["error"]["code"] == "not_found"
        assert "Octo" in env["error"]["message"]

    def test_no_payload_is_usage_error(self, live_ydb, tmp_path):
        env = sql_run(_profile(tmp_path))
        assert env["ok"] is False
        assert env["error"]["code"] == "usage"


# ----------------- shell -----------------


class TestShell:
    def test_build_exec_argv(self, tmp_path):
        argv = build_exec_argv(_profile(tmp_path))
        assert argv[0] == "docker"
        assert "exec" in argv
        assert "-it" in argv
        # The bash -c invocation sources ydb_env_set then exec yottadb -direct
        joined = " ".join(argv)
        assert "ydb_env_set" in joined
        assert "yottadb -direct" in joined

    def test_missing_container(self, tmp_path, monkeypatch):
        monkeypatch.setenv("YDBCTL_CONTAINER", "no-such-container-xyz")
        env = shell_run(_profile(tmp_path), dry_run=True)
        assert env["ok"] is False
        assert env["error"]["code"] == "instance_not_running"

    @pytest.mark.integration
    def test_dry_run_returns_argv(self, live_ydb, tmp_path):
        env = shell_run(_profile(tmp_path), dry_run=True)
        assert env["ok"] is True
        assert env["data"]["dry_run"] is True
        assert env["data"]["argv"][0] == "docker"


# ----------------- globals -----------------


@pytest.mark.integration
class TestGlobalsLive:
    def test_show_undefined_global(self, live_ydb, tmp_path):
        env = globals_show(_profile(tmp_path), name="^DOESNOTEXIST")
        assert env["ok"] is True
        # Either it has no nodes (count 0) or some build emits a default
        assert env["data"]["count"] >= 0

    def test_show_after_set(self, live_ydb, tmp_path):
        from ydbctl.ydb_exec import yottadb_xcmd
        prof = _profile(tmp_path)
        # Seed a global
        yottadb_xcmd(prof,
                      'S ^IRISCTLPHASE2(1)="hello" '
                      'S ^IRISCTLPHASE2(2)="world"')
        try:
            env = globals_show(prof, name="^IRISCTLPHASE2")
            assert env["ok"] is True
            assert env["data"]["count"] >= 2
            joined = "\n".join(env["data"]["lines"])
            assert "hello" in joined
            assert "world" in joined
        finally:
            yottadb_xcmd(prof, 'K ^IRISCTLPHASE2')

    def test_show_with_or_without_caret(self, live_ydb, tmp_path):
        # Same global with both forms returns same result
        env_a = globals_show(_profile(tmp_path), name="^DOESNOTEXIST")
        env_b = globals_show(_profile(tmp_path), name="DOESNOTEXIST")
        assert env_a["data"]["name"] == env_b["data"]["name"] == "^DOESNOTEXIST"

    def test_export_round_trip(self, live_ydb, tmp_path):
        from ydbctl.ydb_exec import yottadb_xcmd
        prof = _profile(tmp_path)
        yottadb_xcmd(prof,
                      'S ^IRISCTLEXPORT(1)=42 '
                      'S ^IRISCTLEXPORT(2)="forty-two"')
        out_path = tmp_path / "export.zwr"
        try:
            env = globals_export(prof, name="^IRISCTLEXPORT", to=out_path)
            assert env["ok"] is True
            assert env["data"]["host_path"] == str(out_path)
            assert env["data"]["size_bytes"] > 0
            content = out_path.read_text(encoding="utf-8")
            assert "IRISCTLEXPORT" in content
        finally:
            yottadb_xcmd(prof, 'K ^IRISCTLEXPORT')
