"""Tests for `ydbctl repl *` — replication wrappers.

The live `ydb-test` container has no replication configured, so:
- `source checkhealth`, `source showbacklog`, `receiver checkhealth`
  return clean `not_found` envelopes (translated from REPLINSTACC).
- `instance create --root-primary` actually works (mupip writes a .repl
  file). Marked @slow because it mutates state.
- `rollback` requires --yes; we test the refusal path.
"""

from __future__ import annotations

import pytest

from ydbctl.commands.repl import (
    instance_create,
    receiver_checkhealth,
    rollback,
    source_checkhealth,
    source_showbacklog,
)
from ydbctl.config import load_profile


def _profile(tmp_path):
    return load_profile(config_path=tmp_path / "missing.toml")


@pytest.mark.integration
class TestReplStatusUnconfigured:
    def test_source_checkhealth(self, live_ydb, tmp_path):
        env = source_checkhealth(_profile(tmp_path))
        assert env["ok"] is False
        assert env["error"]["code"] == "not_found"
        assert "not configured" in env["error"]["message"]

    def test_source_showbacklog(self, live_ydb, tmp_path):
        env = source_showbacklog(_profile(tmp_path))
        assert env["ok"] is False
        assert env["error"]["code"] == "not_found"

    def test_receiver_checkhealth(self, live_ydb, tmp_path):
        env = receiver_checkhealth(_profile(tmp_path))
        assert env["ok"] is False
        assert env["error"]["code"] == "not_found"


class TestInstanceCreateValidation:
    def test_no_role(self, tmp_path):
        env = instance_create(_profile(tmp_path), name="primary")
        assert env["ok"] is False
        assert env["error"]["code"] == "usage"

    def test_both_roles(self, tmp_path):
        env = instance_create(_profile(tmp_path), name="primary",
                                root_primary=True, propagate_primary=True)
        assert env["error"]["code"] == "usage"


class TestRollbackGuards:
    def test_refuses_without_yes(self, tmp_path):
        env = rollback(_profile(tmp_path), fetchresync_port=4000)
        assert env["ok"] is False
        assert env["error"]["code"] == "usage"
