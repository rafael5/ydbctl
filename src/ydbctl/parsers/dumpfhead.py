"""Parser for `mupip dumpfhead -file <dat>` output.

The output is a flat list of `record("<key>")=<value>` lines, one per
file-header field. Keys typically have a `sgmnt_data.` prefix that we
strip on the way in. Values are integers (`123`), hex strings (`"0x..."`),
or `$C(...)` byte-array literals (kept as raw strings).
"""

from __future__ import annotations

import re
from typing import Any

_LINE_RE = re.compile(r'^record\("([^"]+)"\)=(.+)$')


def parse_dumpfhead(text: str) -> dict[str, Any]:
    """Parse dumpfhead text → flat dict.

    Keys are de-prefixed (`sgmnt_data.X` → `X`). Values are ints when
    they look numeric, otherwise strings.
    """
    out: dict[str, Any] = {}
    for raw_line in text.splitlines():
        m = _LINE_RE.match(raw_line.strip())
        if m is None:
            continue
        key, val = m.group(1), m.group(2).strip()
        if key.startswith("sgmnt_data."):
            key = key[len("sgmnt_data."):]
        out[key] = _parse_value(val)
    return out


def _parse_value(val: str) -> Any:
    # Quoted hex/strings: "0x..." or "anything"
    if val.startswith('"') and val.endswith('"'):
        return val[1:-1]
    # $C(...) byte arrays — keep as raw string for fidelity
    if val.startswith("$C(") or val.startswith("$ZCH"):
        return val
    # Plain integer
    try:
        return int(val)
    except ValueError:
        pass
    # Float?
    try:
        return float(val)
    except ValueError:
        pass
    return val


def dumpfhead_summary(rec: dict[str, Any]) -> dict[str, Any]:
    """Pluck the high-value fields most callers want from a dumpfhead record."""
    def _bool(v: Any) -> bool:
        return bool(v) and v != 0

    return {
        "block_size_bytes": rec.get("blk_size"),
        "total_blocks": rec.get("trans_hist.total_blks"),
        "free_blocks": rec.get("trans_hist.free_blocks"),
        "transaction_number": rec.get("trans_hist.curr_tn"),
        "early_transaction_number": rec.get("trans_hist.early_tn"),
        "access_method": _access_method_name(rec.get("acc_meth")),
        "fully_upgraded": _bool(rec.get("fully_upgraded")),
        "abandoned_kills": rec.get("abandoned_kills", 0),
        "creation": rec.get("creation.date_time"),
        "last_inc_backup": rec.get("last_inc_backup"),
        "bplmap": rec.get("bplmap"),
    }


def _access_method_name(code: Any) -> str | None:
    # mupip convention: 0=BG, 1=MM (per YDB docs)
    if code == 0:
        return "BG"
    if code == 1:
        return "MM"
    if code is None:
        return None
    return str(code)
