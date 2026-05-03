"""Phase 3 commands.

Covers: integ, reorg, freeze, locks, rundown, recover, backup, restore.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ydbctl.commands.backup import run as backup_run
from ydbctl.commands.freeze import run as freeze_run
from ydbctl.commands.integ import run as integ_run
from ydbctl.commands.locks import clear as locks_clear
from ydbctl.commands.locks import show as locks_show
from ydbctl.commands.recover import run as recover_run
from ydbctl.commands.reorg import run as reorg_run
from ydbctl.commands.restore import run as restore_run
from ydbctl.commands.rundown import run as rundown_run
from ydbctl.config import load_profile


def _profile(tmp_path):
    return load_profile(config_path=tmp_path / "missing.toml")


# ----------------- integ -----------------


@pytest.mark.integration
class TestInteg:
    def test_default_fast_passes(self, live_ydb, tmp_path):
        env = integ_run(_profile(tmp_path))
        assert env["ok"] is True
        assert env["data"]["mode"] == "fast"
        assert env["data"]["all_ok"] is True
        assert env["data"]["regions_checked"] >= 1
        # Default region must be present
        names = {r["region"] for r in env["data"]["regions"]}
        assert "DEFAULT" in names

    def test_full_mode(self, live_ydb, tmp_path):
        env = integ_run(_profile(tmp_path), full=True)
        assert env["ok"] is True
        assert env["data"]["mode"] == "full"

    def test_specific_region(self, live_ydb, tmp_path):
        env = integ_run(_profile(tmp_path), region="DEFAULT")
        assert env["ok"] is True
        names = {r["region"] for r in env["data"]["regions"]}
        assert "DEFAULT" in names


# ----------------- reorg -----------------


@pytest.mark.integration
class TestReorg:
    def test_default(self, live_ydb, tmp_path):
        env = reorg_run(_profile(tmp_path))
        assert env["ok"] is True
        # On a fresh DB there may be 0 globals; just verify shape
        assert "globals_processed" in env["data"]
        assert "total_blocks_processed" in env["data"]


# ----------------- freeze -----------------


@pytest.mark.integration
class TestFreeze:
    def test_on_then_off(self, live_ydb, tmp_path):
        prof = _profile(tmp_path)
        # Turn on
        env_on = freeze_run(prof, on=True, region="DEFAULT")
        assert env_on["ok"] is True
        assert env_on["data"]["action"] == "on"
        try:
            states = {r["state"] for r in env_on["data"]["regions"]}
            assert "FROZEN" in states
        finally:
            # Always unfreeze, even if assertions fail
            env_off = freeze_run(prof, off=True, region="DEFAULT")
            assert env_off["ok"] is True
            states = {r["state"] for r in env_off["data"]["regions"]}
            assert "UNFROZEN" in states

    def test_no_flag_is_usage_error(self, live_ydb, tmp_path):
        env = freeze_run(_profile(tmp_path))
        assert env["ok"] is False
        assert env["error"]["code"] == "usage"

    def test_both_flags_is_usage_error(self, live_ydb, tmp_path):
        env = freeze_run(_profile(tmp_path), on=True, off=True)
        assert env["ok"] is False
        assert env["error"]["code"] == "usage"


# ----------------- locks -----------------


@pytest.mark.integration
class TestLocksShow:
    def test_show_returns_envelope(self, live_ydb, tmp_path):
        env = locks_show(_profile(tmp_path))
        assert env["ok"] is True
        # On a fresh DB there's no LOCK held — any_locks should be False
        assert "any_locks" in env["data"]
        assert "raw" in env["data"]


@pytest.mark.integration
class TestLocksClearGuards:
    def test_refuses_without_yes(self, live_ydb, tmp_path):
        env = locks_clear(_profile(tmp_path))
        assert env["ok"] is False
        assert env["error"]["code"] == "usage"

    def test_dry_run_returns_plan(self, live_ydb, tmp_path):
        env = locks_clear(_profile(tmp_path), dry_run=True)
        assert env["ok"] is True
        assert env["data"]["dry_run"] is True
        assert "lke_input" in env["data"]


# ----------------- rundown -----------------


@pytest.mark.integration
class TestRundown:
    def test_default_region(self, live_ydb, tmp_path):
        env = rundown_run(_profile(tmp_path), region="DEFAULT")
        assert env["ok"] is True
        # At least the DEFAULT region's DAT should appear
        joined = "\n".join(env["data"]["files_run_down"])
        assert "yottadb.dat" in joined or env["data"]["count"] >= 1


# ----------------- recover -----------------


@pytest.mark.integration
class TestRecover:
    def test_default_does_not_raise(self, live_ydb, tmp_path):
        env = recover_run(_profile(tmp_path), region="DEFAULT")
        # On a clean DB, recover may report nothing to do or success.
        # Either way, the envelope shape should be well-formed.
        assert "command" in env
        assert env["command"] == "recover"


# ----------------- backup -----------------


@pytest.mark.integration
class TestBackup:
    def test_dry_run(self, live_ydb, tmp_path):
        env = backup_run(_profile(tmp_path),
                          region="DEFAULT",
                          to=tmp_path / "out",
                          dry_run=True)
        assert env["ok"] is True
        assert env["data"]["dry_run"] is True
        joined = "\n".join(env["data"]["steps"])
        assert "mupip" in joined
        assert "docker cp" in joined

    def test_real_backup_round_trip(self, live_ydb, tmp_path):
        out_dir = tmp_path / "bk"
        env = backup_run(_profile(tmp_path),
                          region="DEFAULT",
                          to=out_dir,
                          online=True)
        assert env["ok"] is True, env
        host_path = Path(env["data"]["host_path"])
        assert host_path.exists()
        assert env["data"]["size_bytes"] > 1000
        # Bytestream files start with a YDB magic; just verify non-empty
        assert host_path.stat().st_size == env["data"]["size_bytes"]


# ----------------- restore (cheap paths only) -----------------


@pytest.mark.integration
class TestRestoreGuards:
    def test_refuses_without_yes(self, live_ydb, tmp_path):
        f = tmp_path / "fake.bk"
        f.write_bytes(b"x")
        env = restore_run(_profile(tmp_path),
                           source=f,
                           target_dat="/data/r2.07_x86_64/g/yottadb.dat")
        assert env["ok"] is False
        assert env["error"]["code"] == "usage"

    def test_missing_source(self, live_ydb, tmp_path):
        env = restore_run(_profile(tmp_path),
                           source=tmp_path / "nope.bk",
                           target_dat="/tmp/nowhere.dat",
                           yes=True, dry_run=True)
        assert env["ok"] is False
        assert env["error"]["code"] == "not_found"

    def test_dry_run_returns_steps(self, live_ydb, tmp_path):
        f = tmp_path / "fake.bk"
        f.write_bytes(b"x")
        env = restore_run(_profile(tmp_path), source=f,
                           target_dat="/data/r2.07_x86_64/g/yottadb.dat",
                           dry_run=True)
        assert env["ok"] is True
        joined = "\n".join(env["data"]["steps"])
        assert "docker cp" in joined
        assert "mupip restore" in joined


# ----------------- restore round-trip (slow) -----------------


@pytest.mark.integration
@pytest.mark.slow
class TestRestoreRoundTrip:
    """Real backup → restore — exercises the full mupip restore path.

    `mupip restore` enforces TN-alignment: the DB must be at the same
    transaction number where the bytestream begins. After a backup,
    any subsequent write (including the journal-switch the backup
    itself triggers) advances the DB's TN, so a backup-then-restore
    round-trip in the same session is *expected* to fail with
    `MUPRESTERR`. This test verifies the wrapper handles BOTH paths
    cleanly: ok=True on a fresh align, well-formed error on TN drift.
    """

    def test_path_exercises_wrapper(self, live_ydb, tmp_path):
        prof = _profile(tmp_path)
        out_dir = tmp_path / "bk"

        bk_env = backup_run(prof, region="DEFAULT", to=out_dir, online=True)
        assert bk_env["ok"] is True
        bk_path = Path(bk_env["data"]["host_path"])

        target = "/data/r2.07_x86_64/g/yottadb.dat"
        rs_env = restore_run(prof, source=bk_path, target_dat=target,
                              yes=True)

        if rs_env["ok"]:
            integ_env = integ_run(prof, region="DEFAULT")
            assert integ_env["data"]["all_ok"] is True
        else:
            assert rs_env["error"]["code"] == "ydb_error"
            assert ("MUPRESTERR" in rs_env["error"]["message"]
                    or "TN" in rs_env["error"]["message"])
