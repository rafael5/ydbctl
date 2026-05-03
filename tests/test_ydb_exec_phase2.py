"""Phase 2 additions to ydb_exec: M execution + Octo SQL."""

from __future__ import annotations

import pytest

from ydbctl.config import load_profile
from ydbctl.ydb_exec import (
    YdbError,
    ensure_halt,
    has_octo,
    yottadb_direct,
    yottadb_run_entry,
    yottadb_xcmd,
)


def _profile(tmp_path):
    return load_profile(config_path=tmp_path / "missing.toml")


# ----------------- HALT injection (unit) -----------------


class TestEnsureHalt:
    def test_appends_halt_when_missing(self):
        out = ensure_halt('W "x",!')
        assert out.rstrip().endswith("HALT")

    def test_already_ends_with_halt(self):
        out = ensure_halt('W "x",!\nHALT')
        assert out.lower().count("halt") == 1

    def test_replaces_trailing_quit(self):
        out = ensure_halt('W "x",!\nQUIT')
        assert "QUIT" not in out.split("\n")[-1].upper() or "HALT" in out
        assert out.rstrip().endswith("HALT")

    def test_replaces_trailing_q(self):
        out = ensure_halt('W "x",!\n Q')
        assert out.rstrip().endswith("HALT")


# ----------------- yottadb_xcmd against live container ---


@pytest.mark.integration
class TestYottadbXcmd:
    def test_simple_write(self, live_ydb, tmp_path):
        out = yottadb_xcmd(_profile(tmp_path), 'W "hello-xcmd",!')
        assert "hello-xcmd" in out

    def test_arithmetic(self, live_ydb, tmp_path):
        out = yottadb_xcmd(_profile(tmp_path), 'W 2+3,!')
        assert "5" in out

    def test_multi_command(self, live_ydb, tmp_path):
        out = yottadb_xcmd(_profile(tmp_path),
                            'S X=10 S Y=20 W X+Y,!')
        assert "30" in out

    def test_syntax_error_raises(self, live_ydb, tmp_path):
        with pytest.raises(YdbError):
            yottadb_xcmd(_profile(tmp_path),
                          'this is definitely not valid M code')

    def test_global_set_and_zw(self, live_ydb, tmp_path):
        prof = _profile(tmp_path)
        # Set a global, then read it back via a separate call
        yottadb_xcmd(prof, 'S ^IRISCTLTEST=42')
        out = yottadb_xcmd(prof, 'W ^IRISCTLTEST,!')
        assert "42" in out
        # Cleanup
        yottadb_xcmd(prof, 'K ^IRISCTLTEST')


# ----------------- yottadb_direct (heredoc mode) -----------------


@pytest.mark.integration
class TestYottadbDirect:
    def test_basic_multiline(self, live_ydb, tmp_path):
        prof = _profile(tmp_path)
        script = '\n'.join([
            'S X=7',
            'S Y=8',
            'W X*Y,!',
        ])
        out = yottadb_direct(prof, script)
        assert "56" in out

    def test_strips_prompts(self, live_ydb, tmp_path):
        prof = _profile(tmp_path)
        out = yottadb_direct(prof, 'W "irisctl-direct",!')
        # The output should NOT include literal "YDB>" prompts
        assert "irisctl-direct" in out
        assert "YDB>" not in out

    def test_quit_replaced_with_halt(self, live_ydb, tmp_path):
        # Should not hang — QUIT auto-replaced with HALT
        out = yottadb_direct(_profile(tmp_path),
                              'W "ok-quit",!\nQUIT', timeout=10)
        assert "ok-quit" in out


# ----------------- has_octo + octo_exec -----------------


@pytest.mark.integration
class TestOctoDetection:
    def test_has_octo_returns_bool(self, live_ydb, tmp_path):
        # Base image has no Octo — expect False
        assert has_octo(_profile(tmp_path)) is False

    def test_octo_exec_raises_when_missing(self, live_ydb, tmp_path):
        from ydbctl.ydb_exec import octo_exec
        with pytest.raises(YdbError, match="Octo CLI not installed"):
            octo_exec(_profile(tmp_path), "SELECT 1")


# ----------------- run-entry -----------------


@pytest.mark.integration
class TestYottadbRunEntry:
    def test_run_xcmd_via_run(self, live_ydb, tmp_path):
        # %XCMD is itself reachable as a -run target
        out = yottadb_run_entry(_profile(tmp_path),
                                  "%XCMD", 'W "hi-entry",!')
        assert "hi-entry" in out
