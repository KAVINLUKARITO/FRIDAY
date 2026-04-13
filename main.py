"""
main.py  Compatibility shim.

The maintained entrypoint for this project is runner.py.

Usage:
    python runner.py "your task here"
    python runner.py "your task here" --json

This file exists to prevent import errors from any tooling
that expects main.py. It delegates to runner.py.
"""
import subprocess
import sys


def main() -> None:
    args = sys.argv[1:]
    result = subprocess.run(
        [sys.executable, "runner.py"] + args,
        check=False,
    )
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
