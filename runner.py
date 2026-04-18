"""Alias for friday_runner.py  maintained for compatibility."""
from friday_runner import *  # noqa: F401, F403
from aiworker.runner import run_bug_bounty, run_trading_lab  # noqa: F401

if __name__ == "__main__":
    from friday_runner import main
    main()
