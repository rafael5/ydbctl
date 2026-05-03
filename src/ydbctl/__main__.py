"""Allow `python -m ydbctl …` invocation."""

from ydbctl.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
