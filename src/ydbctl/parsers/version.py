"""Parser for `yottadb -version` output."""

from __future__ import annotations

import re

_LINE_RE = re.compile(r'^([^:]+):\s+(.+?)\s*$')

# Display label → JSON-key remapping (snake_case)
_KEY_MAP = {
    "yottadb release": "release",
    "upstream base version": "upstream",
    "platform": "platform",
    "build date/time": "build_date_time",
    "build commit sha": "build_commit_sha",
    "compiler": "compiler",
    "compiler version": "compiler_version",
    "build type": "build_type",
}


def parse_version(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        m = _LINE_RE.match(raw)
        if m is None:
            continue
        label = m.group(1).strip().lower()
        value = m.group(2).strip()
        key = _KEY_MAP.get(label, _normalize(label))
        out[key] = value
    return out


def _normalize(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label).strip("_")
