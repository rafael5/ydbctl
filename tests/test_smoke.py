from ydbctl import __version__


def test_version():
    assert __version__ == "0.1.0"


def test_imports():
    """Smoke: every foundational module imports cleanly."""
    import ydbctl  # noqa: F401
    import ydbctl.config  # noqa: F401
    import ydbctl.docker_api  # noqa: F401
    import ydbctl.output  # noqa: F401
    import ydbctl.ydb_exec  # noqa: F401

    assert ydbctl.__version__
