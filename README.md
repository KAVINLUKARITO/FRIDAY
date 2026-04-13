# Friday  AGI-Progressive AI Agent

> Friday is a production-grade autonomous task agent with
> episodic memory, self-reflection, and adaptive planning.
> It gets smarter with every run.

## Quick Start

```bash
pip install -r requirements.txt
python friday_runner.py "list files" --json
```

## What Makes Friday Different

- Remembers every task it has ever run
- Learns from failures automatically
- Adapts its planning based on past experience
- Builds a knowledge graph of tools and patterns
- Gets measurably better over time

## CLI Commands

```bash
python friday_runner.py "your task"         # run a task
python friday_runner.py "your task" --json  # JSON output
python friday_runner.py --memory            # show memory
python friday_runner.py --knowledge         # show knowledge
python friday_runner.py --stats             # show stats
python runner.py "your task"                # legacy alias
```

## How to run in 5 steps

1. Create and activate a Python 3.10+ virtual environment.

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

2. Install dependencies.

   ```powershell
   python -m pip install -r requirements.txt
   ```

3. Create local configuration.

   ```powershell
   Copy-Item .env.example .env
   ```

4. Run a sample task.

   ```powershell
   python runner.py
   ```

5. Run your own task.

   ```powershell
   python runner.py "list files"
   python runner.py "read README.md" --json
   ```

## Runtime behavior

The maintained agent path includes CLI task intake, deterministic intent classification, bounded planning, validated tool execution, structured `ToolResult` objects, JSONL memory persistence, global logging, graceful shutdown handling, and a `MAX_ITERATIONS` guard through `AIWORKER_MAX_ITERATIONS`.

Built-in tools:

- `echo`: returns text unchanged.
- `list_files`: lists files below `AIWORKER_BASE_PATH`.
- `read_file`: reads text files below `AIWORKER_BASE_PATH`.
- `http_get`: performs timed HTTP GET requests with structured errors.
- `system_info`: reports Python and platform metadata.

Legacy experimental modules remain in the repository, but `runner.py` is the stable local automation path.
