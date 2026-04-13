# Active Source Layout

This repository currently contains multiple overlapping Python applications. The active paths are not equivalent, and they should not be treated as one coherent package until they are deliberately consolidated.

## Primary root task-agent path

These root files define the maintained deterministic local-first worker described by the root README:

- `runner.py`
- `config.py`
- `planner.py`
- `validator.py`
- `executor.py`
- `verifier.py`
- `storage.py`
- `tools.py`
- `logger.py`
- `eval.py`
- `tests/`

This is the smallest and clearest runnable path in the repository.

## Secondary package path

The `aiworker/` package contains a much larger experimental platform with its own:

- `main.py`
- `runner.py`
- `config.py`
- `requirements.txt`
- `pyproject.toml`
- `tests/`
- many feature subpackages

This package appears to be a separate application family, not just an internal library for the root worker.

## Third project embedded in repo

The `trading_system/` directory is a separate standalone project with its own:

- runtime model
- packaging
- tests
- generated runtime databases

It should be treated as an embedded sibling project, not part of the root worker path.

## Frontend and operational artifacts

- `dashboard/` is a separate frontend project.
- `setup_vps.sh` and `aiworker_vps.yaml` are deployment artifacts.
- `feature-governance-audit.patch`, `REVIEW_AND_PR.md`, `kipping`, and the long malformed filename at repo root are review/import artifacts, not core runtime modules.

## Recommended working rule

Until consolidation happens, use only one app path at a time:

1. Root worker path for the deterministic local-first worker.
2. `aiworker/` package for the larger experimental platform.
3. `trading_system/` for the trading system.

Mixing imports or tests across these paths will create ambiguity and maintenance risk.
