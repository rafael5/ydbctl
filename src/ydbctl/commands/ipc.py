"""`ydbctl ipc` — show shared memory + semaphore state inside the container.

YottaDB-only concern (no IRIS analog). Helps detect orphan IPC keys
left over from an unclean shutdown — those need `mupip rundown` to
clean up before next start.
"""

from __future__ import annotations

import re
from typing import Any

from ydbctl.config import Profile
from ydbctl.output import ErrorCode, error_envelope, success_envelope
from ydbctl.ydb_exec import YdbError, ydb_run


def run(profile: Profile) -> dict[str, Any]:
    try:
        shm_res = ydb_run(profile, "ipcs -m")
        sem_res = ydb_run(profile, "ipcs -s")
    except YdbError as e:
        return error_envelope("ipc", code=ErrorCode.YDB_ERROR, message=str(e))

    shm = _parse_ipcs_table(shm_res["stdout"], kind="shm")
    sem = _parse_ipcs_table(sem_res["stdout"], kind="sem")

    warnings: list[str] = []
    orphan_shm = [s for s in shm if s.get("nattch", 0) == 0]
    if orphan_shm:
        warnings.append(
            f"{len(orphan_shm)} shared-memory segment(s) with nattch=0 "
            "(may be orphan IPC — `mupip rundown -region '*'` to clean)"
        )

    return success_envelope("ipc", {
        "shared_memory": shm,
        "semaphores": sem,
        "shm_count": len(shm),
        "sem_count": len(sem),
    }, warnings=warnings)


# Header regex tolerant of different ipcs versions
_HEADER_RE = re.compile(r"^(key|shmid|semid|owner|perms|bytes|nattch|nsems)",
                          re.IGNORECASE)


def _parse_ipcs_table(text: str, *, kind: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    headers: list[str] | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("---"):
            continue
        if headers is None and _HEADER_RE.match(line):
            headers = line.split()
            continue
        if headers is None:
            continue
        parts = line.split()
        if len(parts) < len(headers):
            continue
        # Limit to header column count; trailing fields can be empty
        record: dict[str, Any] = {}
        for i, h in enumerate(headers):
            v = parts[i] if i < len(parts) else ""
            if h.lower() in ("bytes", "nattch", "nsems"):
                try:
                    record[h.lower()] = int(v)
                    continue
                except ValueError:
                    pass
            record[h.lower()] = v
        record["kind"] = kind
        rows.append(record)
    return rows
