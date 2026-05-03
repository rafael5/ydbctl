"""Tests for the ydbctl JSON-RPC server."""

from __future__ import annotations

import io
import json

import pytest

from ydbctl.config import load_profile
from ydbctl.rpc import (
    METHODS,
    handle_request,
    serve,
)


def _profile(tmp_path):
    return load_profile(config_path=tmp_path / "missing.toml")


# ----------------- handle_request (unit) -----------------


class TestHandleRequest:
    def test_unknown_method(self, tmp_path):
        req = {"jsonrpc": "2.0", "method": "not_a_method", "id": 1}
        resp = handle_request(req, _profile(tmp_path))
        assert resp["error"]["code"] == -32601

    def test_missing_jsonrpc(self, tmp_path):
        req = {"method": "which", "id": 1}
        resp = handle_request(req, _profile(tmp_path))
        assert resp["error"]["code"] == -32600

    def test_which_method(self, tmp_path):
        req = {"jsonrpc": "2.0", "method": "which",
               "params": {"op": "version"}, "id": 7}
        resp = handle_request(req, _profile(tmp_path))
        assert resp["id"] == 7
        assert "result" in resp
        assert resp["result"]["data"]["op"] == "version"

    def test_notification_no_response(self, tmp_path):
        req = {"jsonrpc": "2.0", "method": "which",
               "params": {"op": "version"}}
        resp = handle_request(req, _profile(tmp_path))
        assert resp is None

    def test_registry_includes_all_phases(self):
        for required in (
            # Phase 1
            "status", "version", "ports", "env", "regions", "files",
            "dbinfo", "ipc", "logs", "health", "which",
            # Phase 2
            "exec", "sql", "shell", "globals_show", "globals_export",
            # Phase 3
            "integ", "reorg", "freeze", "locks_show", "locks_clear",
            "rundown", "recover", "backup", "restore",
            # Phase 4
            "vista_rpcbroker", "vista_vistalink", "vista_hl7",
            "vista_journal", "vista_ports",
            # Phase 5
            "repl_source_checkhealth", "repl_receiver_checkhealth",
            "repl_instance_create",
        ):
            assert required in METHODS, f"missing rpc method: {required}"


# ----------------- serve (loop) -----------------


class TestServe:
    def test_one_request(self, tmp_path):
        stdin = io.StringIO(
            json.dumps({"jsonrpc": "2.0", "method": "which",
                        "params": {"op": "version"}, "id": 1}) + "\n"
        )
        stdout = io.StringIO()
        serve(_profile(tmp_path), stdin=stdin, stdout=stdout)
        resp = json.loads(stdout.getvalue().strip())
        assert resp["id"] == 1
        assert "result" in resp

    def test_multiple_requests(self, tmp_path):
        reqs = [
            {"jsonrpc": "2.0", "method": "which", "id": 1,
             "params": {"op": "version"}},
            {"jsonrpc": "2.0", "method": "which", "id": 2,
             "params": {"op": "exec"}},
        ]
        stdin = io.StringIO("\n".join(json.dumps(r) for r in reqs) + "\n")
        stdout = io.StringIO()
        serve(_profile(tmp_path), stdin=stdin, stdout=stdout)
        lines = [ln for ln in stdout.getvalue().splitlines() if ln.strip()]
        assert len(lines) == 2
        assert json.loads(lines[0])["id"] == 1
        assert json.loads(lines[1])["id"] == 2

    def test_invalid_json_emits_parse_error(self, tmp_path):
        stdin = io.StringIO("not json\n")
        stdout = io.StringIO()
        serve(_profile(tmp_path), stdin=stdin, stdout=stdout)
        resp = json.loads(stdout.getvalue().strip())
        assert resp["error"]["code"] == -32700


@pytest.mark.integration
class TestRpcLive:
    def test_version_via_rpc(self, live_ydb, tmp_path):
        req = {"jsonrpc": "2.0", "method": "version", "id": 1}
        resp = handle_request(req, _profile(tmp_path))
        assert resp["result"]["ok"] is True
        assert resp["result"]["data"]["ydb_release"].startswith("r2.")

    def test_regions_via_rpc(self, live_ydb, tmp_path):
        req = {"jsonrpc": "2.0", "method": "regions", "id": 1}
        resp = handle_request(req, _profile(tmp_path))
        assert resp["result"]["ok"] is True
        assert "DEFAULT" in resp["result"]["data"]["regions"]
