# AI Worker

This project is already organized around the active source tree and the generated runtime data:

- `agents/`: bug bounty and trading agent implementations
- `tests/`: pytest suite
- `runtime/`: logs, databases, reports, and temporary test artifacts
- `workspace/`: generated working files and reports
- root `*.py`: shared runtime modules and entry points

Important source files stay in place so imports and execution behavior do not change.

Current note:

- Some `pytest-cache-files-*` directories at the project root were created by earlier test runs.
- They should ideally live under `runtime/test_artifacts/`, but Windows is currently denying move access to those specific folders.
- No source code was moved or changed as part of this cleanup.
