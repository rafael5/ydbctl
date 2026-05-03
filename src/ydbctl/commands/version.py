"""`ydbctl version` — YottaDB engine version + image labels."""

from __future__ import annotations

from typing import Any

from ydbctl import __version__
from ydbctl.config import Profile
from ydbctl.docker_api import DockerError, container_exists, image_labels
from ydbctl.output import ErrorCode, error_envelope, success_envelope
from ydbctl.parsers.version import parse_version
from ydbctl.ydb_exec import YdbError, yottadb_version


def run(profile: Profile) -> dict[str, Any]:
    if not container_exists(profile.container):
        return error_envelope(
            "version",
            code=ErrorCode.INSTANCE_NOT_RUNNING,
            message=f"container {profile.container!r} not found",
            hint="docker ps -a; expected name: " + profile.container,
        )
    try:
        version_text = yottadb_version(profile)
    except YdbError as e:
        return error_envelope("version", code=ErrorCode.YDB_ERROR,
                               message=str(e))

    try:
        labels = image_labels(profile.container)
    except DockerError:
        labels = {}

    parsed = parse_version(version_text)

    return success_envelope("version", {
        "ydbctl_version": __version__,
        "container": profile.container,
        "ydb_release": parsed.get("release", ""),
        "upstream": parsed.get("upstream", ""),
        "platform": parsed.get("platform", ""),
        "build_type": parsed.get("build_type", ""),
        "build_date_time": parsed.get("build_date_time", ""),
        "image_version": labels.get("org.opencontainers.image.version", ""),
    })
