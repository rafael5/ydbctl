"""Tests for `ydbctl vista *` — VistA-on-YottaDB layer.

The live `ydb-test` container is the YottaDB *base* image (no VistA),
so:
- `vista=False` profile (default) — every vista subcommand returns
  `usage` (clean refusal).
- `vista=True` profile (we override via env) — the helper-script lookup
  fails with `not_found` because docker-vista's bin dir doesn't exist
  in the test container. We test that path too.

A truly VistA-on-YottaDB build would be needed for integration tests
that actually start/stop the listeners; those are deferred until
docker-vista-fork's YottaDB image is built locally.
"""

from __future__ import annotations

import pytest

from ydbctl.commands.vista import (
    dispatch,
    hl7,
    journal,
    ports,
    rpcbroker,
    vistalink,
)
from ydbctl.config import load_profile


def _profile(tmp_path):
    return load_profile(config_path=tmp_path / "missing.toml")


def _vista_profile(tmp_path):
    cfg = tmp_path / "c.toml"
    cfg.write_text(
        '[profiles.v]\n'
        'container = "ydb-test"\n'
        'vista = true\n'
        'vista_instance = "foia"\n',
        encoding="utf-8",
    )
    return load_profile(profile="v", config_path=cfg)


# ----------------- profile.vista = false -----------------


class TestVistaDisabled:
    def test_rpcbroker_refused(self, tmp_path):
        env = rpcbroker(_profile(tmp_path), "status")
        assert env["ok"] is False
        assert env["error"]["code"] == "usage"
        assert "vista=true" in env["error"]["message"]

    def test_vistalink_refused(self, tmp_path):
        env = vistalink(_profile(tmp_path))
        assert env["error"]["code"] == "usage"

    def test_hl7_refused(self, tmp_path):
        env = hl7(_profile(tmp_path))
        assert env["error"]["code"] == "usage"

    def test_journal_refused(self, tmp_path):
        env = journal(_profile(tmp_path), "enable")
        assert env["error"]["code"] == "usage"

    def test_ports_refused(self, tmp_path):
        env = ports(_profile(tmp_path))
        assert env["error"]["code"] == "usage"


# ----------------- profile.vista = true, helpers missing -----------------


@pytest.mark.integration
class TestVistaEnabledNoHelpers:
    """vista=true on a non-VistA container — helpers are absent."""

    def test_rpcbroker_status_returns_envelope(self, live_ydb, tmp_path):
        # status doesn't probe helper presence; it probes the port.
        # On a non-VistA container the port is closed → running=False.
        env = rpcbroker(_vista_profile(tmp_path), "status")
        assert env["ok"] is True
        assert env["data"]["running"] is False
        assert env["data"]["service"] == "rpcbroker"
        assert env["data"]["host_port"] == 9430

    def test_rpcbroker_start_returns_not_found(self, live_ydb, tmp_path):
        env = rpcbroker(_vista_profile(tmp_path), "start")
        assert env["ok"] is False
        assert env["error"]["code"] == "not_found"
        assert "rpcbroker.sh" in env["error"]["message"]

    def test_journal_enable_fails_cleanly(self, live_ydb, tmp_path):
        # /home/foia/etc/env doesn't exist → script fails — surfaced cleanly
        env = journal(_vista_profile(tmp_path), "enable")
        # Either ydb_error from the missing source file or usage from
        # an upstream check — both are well-formed envelopes.
        assert env["ok"] is False
        assert env["error"]["code"] in ("ydb_error", "usage", "not_found")

    def test_ports_table(self, live_ydb, tmp_path):
        env = ports(_vista_profile(tmp_path))
        assert env["ok"] is True
        rows = env["data"]["listeners"]
        roles = {r["role"] for r in rows}
        assert {"rpcbroker", "vistalink", "hl7"} <= roles
        # Each row has a reachable bool. Some may be True if another
        # host service occupies the well-known port (e.g. the IRIS
        # foia container's RPC Broker on 9430).
        for r in rows:
            assert isinstance(r["reachable"], bool)
            assert "host_port" in r


# ----------------- dispatch -----------------


class TestDispatch:
    def test_no_subverb(self, tmp_path):
        import argparse
        ns = argparse.Namespace(vista_sub=None)
        env = dispatch(ns, _profile(tmp_path))
        assert env["error"]["code"] == "usage"

    def test_unknown_action(self, tmp_path):
        import argparse
        ns = argparse.Namespace(vista_sub="rpcbroker", action="not-real")
        env = dispatch(ns, _vista_profile(tmp_path))
        assert env["error"]["code"] == "usage"

    def test_unknown_journal_action(self, tmp_path):
        env = journal(_vista_profile(tmp_path), "not-real")
        assert env["error"]["code"] == "usage"
