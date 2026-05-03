"""Test fixtures shared across the suite.

`integration`-marked tests need the live `ydb-test` YottaDB container
running on localhost. The `live_ydb` fixture is the readiness probe.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


def _container_running(name: str) -> bool:
    res = subprocess.run(
        ["docker", "ps", "--filter", f"name={name}", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return name in res.stdout.split()


@pytest.fixture(scope="session")
def live_ydb() -> str:
    """Confirm the ydb-test container is up.

    Returns the container name. Skips dependent tests if not running.
    """
    name = "ydb-test"
    if not _container_running(name):
        pytest.skip(f"container {name!r} is not running")
    return name
