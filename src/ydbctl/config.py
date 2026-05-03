"""Profile / config loading for ydbctl.

Mirrors irisctl/config.py but adapted for YottaDB. No license/auth
concepts at the database layer (YDB is library-not-daemon, Apache 2.0).
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "ydbctl" / "config.toml"


@dataclass
class Profile:
    container: str
    host: str
    data_dir: Path
    ydb_dist: str = "/opt/yottadb/current"
    # Optional service ports (only meaningful if the corresponding
    # listener is started — they're all opt-in)
    gui_port: int = 9080
    gui_stats_port: int = 9081
    rocto_port: int = 1337
    gtcm_port: int = 6789
    # VistA layer (docker-vista-fork's YottaDB build)
    vista: bool = False


_DEFAULTS: dict[str, object] = {
    "container": "ydb-test",
    "host": "127.0.0.1",
    "data_dir": str(Path.home() / "data" / "ydb-test"),
    "ydb_dist": "/opt/yottadb/current",
    "gui_port": 9080,
    "gui_stats_port": 9081,
    "rocto_port": 1337,
    "gtcm_port": 6789,
    "vista": False,
}


def load_profile(
    profile: str | None = None,
    *,
    config_path: Path | None = None,
) -> Profile:
    cfg_path = config_path or DEFAULT_CONFIG_PATH
    file_data = _load_file(cfg_path)

    profile_name = (
        profile
        or os.environ.get("YDBCTL_PROFILE")
        or file_data.get("default_profile")
    )
    profiles_section = file_data.get("profiles", {}) or {}
    if profile_name and profile_name in profiles_section:
        merged = {**_DEFAULTS, **profiles_section[profile_name]}
    elif profile_name and profile_name not in profiles_section and profile:
        raise KeyError(f"profile {profile_name!r} not found in {cfg_path}")
    else:
        merged = dict(_DEFAULTS)

    # Env overrides
    if v := os.environ.get("YDBCTL_CONTAINER"):
        merged["container"] = v
    if v := os.environ.get("YDBCTL_HOST"):
        merged["host"] = v
    if v := os.environ.get("YDBCTL_DATA_DIR"):
        merged["data_dir"] = v
    if v := os.environ.get("YDBCTL_YDB_DIST"):
        merged["ydb_dist"] = v

    return Profile(
        container=str(merged["container"]),
        host=str(merged["host"]),
        data_dir=Path(str(merged["data_dir"])).expanduser(),
        ydb_dist=str(merged["ydb_dist"]),
        gui_port=int(merged.get("gui_port", 9080)),
        gui_stats_port=int(merged.get("gui_stats_port", 9081)),
        rocto_port=int(merged.get("rocto_port", 1337)),
        gtcm_port=int(merged.get("gtcm_port", 6789)),
        vista=bool(merged.get("vista", False)),
    )


def _load_file(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)
