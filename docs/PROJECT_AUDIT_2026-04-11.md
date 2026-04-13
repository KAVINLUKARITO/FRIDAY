# Project Audit - 2026-04-11

## Summary

The repository is functional in parts, but it is not structurally coherent as a single product. It currently contains:

- a root deterministic AI worker application
- a second, much larger `aiworker/` package with overlapping entrypoints and modules
- a standalone `trading_system/` project
- a standalone `dashboard/` frontend
- several pasted review and runtime artifact files mixed into the root

The main source-code problem is not one broken module. It is architectural overlap and naming collision between multiple apps in one repository root.

## Most important findings

### 1. Root module names collide with package module names

The repository has duplicate names at both the root and inside `aiworker/`:

- `config.py`
- `runner.py`
- `logger.py`
- `tools.py`
- `storage.py`
- `validator.py`
- `verifier.py`
- `main.py`

This creates ambiguous import behavior and makes it unclear which application is authoritative during local execution, testing, packaging, and editor indexing.

### 2. `pytest.py` at repo root shadows the real `pytest` package

The file `pytest.py` at repo root is a high-risk compatibility shim. It can shadow the installed `pytest` package and distort test behavior depending on invocation style and import order.

This is one of the highest-priority cleanup items.

### 3. The repository contains at least three separate products

Current products mixed into one tree:

- root local-first worker
- `aiworker/` experimental package
- `trading_system/`

Because they ship their own entrypoints, tests, and packaging metadata, the repository does not currently express a single build graph or ownership model.

### 4. Root test configuration no longer reflects the real tree cleanly

The root `pytest.ini` only points at `tests/`, but the repository also contains:

- `aiworker/tests/`
- `trading_system/tests/`

That means the repo has multiple test universes but only one root test story. This causes confusion about what “green” means.

### 5. Root clutter mixes runtime, review, deploy, and pasted artifacts with source

Examples at repo root:

- `feature-governance-audit.patch`
- `REVIEW_AND_PR.md`
- `kipping`
- `marked with REVIEW_AND_PR.md aiworker feature-governance-audit.patch kipping... venv may be preceded by a number, N`
- `.pytest_cache`
- `pytest-cache-files-*`

These should not live next to active entrypoints.

## Test audit

I ran syntax compilation on the root worker modules successfully.

I also ran the root test suite. The result is:

- 23 tests passed
- 25 tests errored

The observed errors are test-environment failures tied to `tmp_path` setup on this Windows environment, not direct assertion failures in the worker logic. The failing groups are mainly:

- `tests/test_runner.py`
- `tests/test_storage.py`
- `tests/test_tools.py`

These errors prevent a clean full-suite verdict today, so the repository still needs a stable pytest temp-path strategy.

## What to improve next for a more intelligent AI worker

### Source organization

1. Choose one primary application boundary.
   Either:
   - keep the root deterministic worker as the main app, or
   - promote `aiworker/` as the real package and demote the root files to wrappers.

2. Remove or rename import-shadowing files.
   Highest priority:
   - `pytest.py`

3. Separate sibling projects physically.
   Recommended target layout:
   - `apps/worker_root/`
   - `apps/aiworker_platform/`
   - `apps/trading_system/`
   - `apps/dashboard/`
   - `docs/`
   - `runtime/`

### Code intelligence and capability

1. Unify planning and execution interfaces.
   The root worker is deterministic and bounded. The larger `aiworker/` package has many advanced modules. These need a shared contract for:
   - planning
   - tool execution
   - memory
   - governance
   - retry and approval flows

2. Establish one canonical memory layer.
   The repo currently contains multiple state, runtime, memory, and storage concepts. Intelligent behavior will remain fragmented until memory ownership is centralized.

3. Make strategy and routing explicit.
   If the AI worker should choose among:
   - deterministic tools
   - advisory reasoning
   - research
   - multi-agent orchestration
   - trading

   then the repo needs a top-level orchestration contract instead of many parallel subsystems.

4. Add clear capability boundaries.
   The large `aiworker/` package contains many conceptual domains:
   - governance
   - memory
   - research
   - learning
   - autonomy
   - patching
   - safety
   - dashboard

   These need a documented dependency direction. Right now the repository shape suggests feature accumulation rather than a stable architecture.

### Testability

1. Fix the pytest temp-path strategy for Windows.
2. Decide which test suites are authoritative.
3. Prevent runtime artifacts from polluting source roots.
4. Add one smoke command per project that must pass in CI.

## Safe cleanup already applied

I added:

- `docs/ACTIVE_SOURCE_LAYOUT.md`
- `docs/PROJECT_AUDIT_2026-04-11.md`
- broader ignore rules in `.gitignore`

These changes do not alter runtime code.

## Recommended next implementation step

Do this before feature work:

1. Decide the primary app boundary.
2. Rename or remove `pytest.py`.
3. Move review/import artifacts out of the root.
4. Isolate `trading_system/` and `dashboard/` as sibling apps.
5. Rebuild one reliable CI test path for the chosen primary worker.
