"""Tests for the yottadb -version parser."""

from __future__ import annotations

from ydbctl.parsers.version import parse_version

SAMPLE = '''YottaDB release:         r2.07
Upstream base version:   GT.M V7.1-002
Platform:                Linux x86_64
Build date/time:         2026-04-30 21:21
Build commit SHA:        de1fee28a21ca2af3526dce980e8c77ae4f2090c (dirty)
Compiler:                GCC
Compiler Version:        13.3.0
Build Type:              Production
'''


class TestParseVersion:
    def test_release(self):
        v = parse_version(SAMPLE)
        assert v["release"] == "r2.07"

    def test_upstream(self):
        v = parse_version(SAMPLE)
        assert v["upstream"] == "GT.M V7.1-002"

    def test_platform(self):
        v = parse_version(SAMPLE)
        assert v["platform"] == "Linux x86_64"

    def test_build_type(self):
        v = parse_version(SAMPLE)
        assert v["build_type"] == "Production"

    def test_unknown_keys_normalize(self):
        # Extra keys with similar shape get included in the output.
        sample = SAMPLE + "Custom Field:           hello\n"
        v = parse_version(sample)
        assert v.get("custom_field") == "hello"

    def test_empty(self):
        assert parse_version("") == {}
