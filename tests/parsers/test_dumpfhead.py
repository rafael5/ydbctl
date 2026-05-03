"""Tests for the dumpfhead parser."""

from __future__ import annotations

from ydbctl.parsers.dumpfhead import parse_dumpfhead

SAMPLE = '''record("sgmnt_data.abandoned_kills")=0
record("sgmnt_data.acc_meth")=1
record("sgmnt_data.blk_size")=4096
record("sgmnt_data.bplmap")=512
record("sgmnt_data.basedb_fname")=$C(0,0,0)
record("sgmnt_data.creation.date_time")="0x0064EAB2"
record("sgmnt_data.fully_upgraded")=1
record("sgmnt_data.last_inc_backup")="0x0000000000000000"
record("sgmnt_data.problksplit")=0
record("sgmnt_data.trans_hist.curr_tn")="0x0000000000000005"
record("sgmnt_data.trans_hist.early_tn")="0x0000000000000005"
record("sgmnt_data.trans_hist.free_blocks")=9998
record("sgmnt_data.trans_hist.total_blks")=10000
'''


class TestParseDumpfhead:
    def test_basic_fields(self):
        rec = parse_dumpfhead(SAMPLE)
        assert rec["abandoned_kills"] == 0
        assert rec["acc_meth"] == 1
        assert rec["blk_size"] == 4096
        assert rec["bplmap"] == 512

    def test_strips_sgmnt_data_prefix(self):
        rec = parse_dumpfhead(SAMPLE)
        # No raw "sgmnt_data.X" keys; the prefix is stripped
        assert "sgmnt_data.blk_size" not in rec
        assert "blk_size" in rec

    def test_string_value(self):
        rec = parse_dumpfhead(SAMPLE)
        # Hex-string values stay strings
        assert rec["creation.date_time"] == "0x0064EAB2"

    def test_zc_values_dropped(self):
        # $C(...) byte-array literals can't be cleanly typed; they become strings.
        rec = parse_dumpfhead(SAMPLE)
        assert "basedb_fname" in rec
        assert isinstance(rec["basedb_fname"], str)

    def test_nested_keys_preserved(self):
        rec = parse_dumpfhead(SAMPLE)
        # Dotted nested fields stay flat with their dot path
        assert rec["trans_hist.curr_tn"] == "0x0000000000000005"
        assert rec["trans_hist.total_blks"] == 10000

    def test_summary_helper(self):
        from ydbctl.parsers.dumpfhead import dumpfhead_summary
        s = dumpfhead_summary(parse_dumpfhead(SAMPLE))
        # Block size + counts surface as a clean summary
        assert s["block_size_bytes"] == 4096
        assert s["total_blocks"] == 10000
        assert s["free_blocks"] == 9998
        assert s["fully_upgraded"] is True
        assert s["transaction_number"] == "0x0000000000000005"


class TestEmptyInput:
    def test_empty_returns_empty_dict(self):
        assert parse_dumpfhead("") == {}

    def test_garbage_returns_empty(self):
        assert parse_dumpfhead("this is not a dumpfhead") == {}
