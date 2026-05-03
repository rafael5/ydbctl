"""Unit tests for the output envelope module (no subprocess)."""

from __future__ import annotations

import json

from ydbctl.output import (
    ErrorCode,
    error_envelope,
    exit_code_for,
    render_human,
    render_json,
    success_envelope,
)


class TestSuccessEnvelope:
    def test_minimal_shape(self):
        env = success_envelope("regions", {"count": 4})
        assert env["v"] == 1
        assert env["ok"] is True
        assert env["command"] == "regions"
        assert env["data"] == {"count": 4}
        assert env["warnings"] == []

    def test_with_warnings(self):
        env = success_envelope("ipc", {}, warnings=["orphan"])
        assert env["warnings"] == ["orphan"]


class TestErrorEnvelope:
    def test_basic(self):
        env = error_envelope(
            "ipc", code=ErrorCode.IPC_ORPHANS,
            message="3 orphan keys", hint="ydbctl rundown",
        )
        assert env["ok"] is False
        assert env["error"]["code"] == "ipc_orphans"
        assert env["error"]["hint"] == "ydbctl rundown"


class TestExitCodes:
    def test_per_plan(self):
        assert exit_code_for(ErrorCode.OK) == 0
        assert exit_code_for(ErrorCode.INTERNAL) == 1
        assert exit_code_for(ErrorCode.USAGE) == 2
        assert exit_code_for(ErrorCode.INSTANCE_NOT_RUNNING) == 3
        # Distinct from IRIS: ipc_orphans replaces license_exhausted at exit 4
        assert exit_code_for(ErrorCode.IPC_ORPHANS) == 4
        assert exit_code_for(ErrorCode.AUTH_REQUIRED) == 5
        assert exit_code_for(ErrorCode.AUTH_FAILED) == 5
        assert exit_code_for(ErrorCode.NOT_FOUND) == 6
        assert exit_code_for(ErrorCode.YDB_ERROR) == 7
        assert exit_code_for(ErrorCode.DOCKER_ERROR) == 8
        assert exit_code_for(ErrorCode.NETWORK_ERROR) == 9


class TestRender:
    def test_json_compact_default(self):
        env = success_envelope("x", {"a": 1})
        out = render_json(env)
        assert "\n" not in out
        assert json.loads(out) == env

    def test_json_pretty(self):
        env = success_envelope("x", {"a": 1})
        out = render_json(env, pretty=True)
        assert "\n" in out

    def test_human_dict(self):
        env = success_envelope("x", {"a": 1, "b": 2})
        out = render_human(env)
        assert "a" in out and "1" in out
        assert "b" in out and "2" in out

    def test_human_list(self):
        env = success_envelope("rows", [{"k": 1}, {"k": 2}])
        out = render_human(env)
        # The two values appear
        assert "1" in out and "2" in out

    def test_human_error(self):
        env = error_envelope("x", code=ErrorCode.NOT_FOUND, message="missing")
        out = render_human(env)
        assert "ERROR" in out.upper()
        assert "missing" in out
