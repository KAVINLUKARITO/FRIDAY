from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from config import cfg

FASTAPI_IMPORT_ERROR: Exception | None = None

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
    from fastapi.templating import Jinja2Templates
    from fastapi.requests import Request
except Exception as exc:  # pragma: no cover - optional dependency surface
    FASTAPI_IMPORT_ERROR = exc
    FastAPI = None  # type: ignore[assignment]
    HTTPException = RuntimeError  # type: ignore[assignment]
    FileResponse = HTMLResponse = JSONResponse = PlainTextResponse = StreamingResponse = object  # type: ignore[assignment]
    Request = object  # type: ignore[assignment]
    Jinja2Templates = None  # type: ignore[assignment]


RUNS_DIR = Path("observability/runs")
RUN_LOG = Path("observability/agent_run.jsonl")
MEMORY_PATH = Path("memory/agent_memory.json")
REFLECTIONS_PATH = Path("memory/reflections.json")
GOALS_PATH = Path("memory/goals.json")
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _list_runs() -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for path in sorted(RUNS_DIR.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        payload = _load_json(path, {})
        if not isinstance(payload, dict):
            continue
        result = payload.get("result", {})
        trace = payload.get("trace", [])
        if not isinstance(result, dict) or not isinstance(trace, list):
            continue
        runs.append(
            {
                "run_id": payload.get("run_id", path.stem),
                "task": result.get("task", "unknown"),
                "timestamp": path.stat().st_mtime,
                "steps_completed": sum(1 for item in trace if isinstance(item, dict) and item.get("event") == "TOOL_SELECTED"),
                "goal_achieved": bool(result.get("goal_achieved", False)),
                "failures": len(result.get("failures", [])) if isinstance(result.get("failures"), list) else 0,
            }
        )
    return runs


def _render_trace_rows(trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in trace:
        if not isinstance(item, dict):
            continue
        event = str(item.get("event", ""))
        data = item.get("data", {})
        css_class = ""
        if event == "CRITIC_SCORE":
            decision = str((data or {}).get("verdict", {}).get("decision", ""))
            css_class = "good" if decision == "correct" else "bad"
        elif event == "STEP_FAILED":
            css_class = "warn"
        elif event == "REPLAN":
            css_class = "replan"
        rows.append(
            {
                "timestamp": item.get("ts", ""),
                "event": event,
                "data": json.dumps(data, indent=2, default=str)[:3000],
                "css_class": css_class,
            }
        )
    return rows


def _markdown_report(run_id: str, payload: dict[str, Any]) -> str:
    result = payload.get("result", {}) if isinstance(payload.get("result"), dict) else {}
    trace = payload.get("trace", []) if isinstance(payload.get("trace"), list) else []
    lines = [
        "# AIWorker Run Report",
        f"*Run ID:* {run_id}",
        f"*Task:* {result.get('task', 'unknown')}",
        f"*Goal Achieved:* {result.get('goal_achieved', False)}",
        "## Steps",
        "| Step | Tool | Decision | Score |",
        "| --- | --- | --- | --- |",
    ]
    tool_events = [item for item in trace if isinstance(item, dict) and item.get("event") == "TOOL_SELECTED"]
    critic_events = [item for item in trace if isinstance(item, dict) and item.get("event") == "CRITIC_SCORE"]
    for index, tool_event in enumerate(tool_events, start=1):
        tool_data = tool_event.get("data", {}) if isinstance(tool_event.get("data"), dict) else {}
        critic_data = critic_events[index - 1].get("data", {}) if index - 1 < len(critic_events) and isinstance(critic_events[index - 1].get("data"), dict) else {}
        verdict = critic_data.get("verdict", {}) if isinstance(critic_data.get("verdict"), dict) else {}
        lines.append(
            f"| {index} | {tool_data.get('tool', '')} | {verdict.get('decision', '')} | {verdict.get('score', '')} |"
        )
    return "\n".join(lines) + "\n"


if FastAPI is not None:
    app = FastAPI(title="AIWorker Dashboard")
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        runs = _list_runs()
        stats = {
            "total_runs": len(runs),
            "goals_achieved": sum(1 for run in runs if run["goal_achieved"]),
            "total_failures": sum(run["failures"] for run in runs),
        }
        return templates.TemplateResponse(request, "index.html", {"request": request, "runs": runs, "stats": stats})

    @app.get("/run/{run_id}", response_class=HTMLResponse)
    def run_detail(run_id: str, request: Request) -> HTMLResponse:
        path = RUNS_DIR / f"{run_id}.json"
        payload = _load_json(path, None)
        if not isinstance(payload, dict):
            raise HTTPException(status_code=404, detail="run not found")
        return templates.TemplateResponse(
            request,
            "run_detail.html",
            {
                "request": request,
                "run_id": run_id,
                "result": payload.get("result", {}),
                "trace_rows": _render_trace_rows(payload.get("trace", [])),
            },
        )

    @app.get("/memory", response_class=HTMLResponse)
    def memory_view(request: Request) -> HTMLResponse:
        memory_records = _load_json(MEMORY_PATH, [])
        reflections = _load_json(REFLECTIONS_PATH, [])
        return templates.TemplateResponse(
            request,
            "memory.html",
            {"request": request, "memory_records": memory_records, "reflections": reflections},
        )

    @app.get("/goals", response_class=HTMLResponse)
    def goals_view() -> HTMLResponse:
        goals = _load_json(GOALS_PATH, [])
        if not isinstance(goals, list):
            goals = []
        rows = []
        for goal in goals:
            if not isinstance(goal, dict):
                continue
            results = goal.get("results", [])
            if not isinstance(results, list):
                results = []
            links = []
            for item in results:
                if not isinstance(item, dict):
                    continue
                run_id = str(item.get("run_id", "")).strip()
                sub_goal = str(item.get("sub_goal", "sub-goal"))
                if run_id:
                    links.append(f"<a href='/run/{run_id}'>{sub_goal}</a>")
                else:
                    links.append(sub_goal)
            rows.append(
                {
                    "goal": str(goal.get("goal", "")),
                    "sub_goals": len(goal.get("sub_goals", [])) if isinstance(goal.get("sub_goals"), list) else 0,
                    "achieved": int(goal.get("total_achieved", 0)),
                    "timestamp": str(goal.get("timestamp", "")),
                    "links": ", ".join(links),
                }
            )
        body = (
            "<!doctype html><html><body style='background:#111;color:#eee;font-family:monospace'>"
            "<h1>Goals</h1>"
            "<table border='1' cellspacing='0' cellpadding='6'>"
            "<tr><th>Goal</th><th>Sub-goals</th><th>Achieved</th><th>Runs</th><th>Timestamp</th></tr>"
            + "".join(
                f"<tr><td>{row['goal']}</td><td>{row['sub_goals']}</td><td>{row['achieved']}</td><td>{row['links']}</td><td>{row['timestamp']}</td></tr>"
                for row in rows
            )
            + "</table></body></html>"
        )
        return HTMLResponse(body)

    @app.get("/agents", response_class=HTMLResponse)
    def agents_view() -> HTMLResponse:
        try:
            from agents.queue import TaskQueue
            from agents.result_store import ResultStore
        except Exception as exc:
            return HTMLResponse(f"<html><body><pre>agents unavailable: {exc}</pre></body></html>", status_code=500)
        queue = TaskQueue()
        store = ResultStore()
        body = {
            "pending": len(queue.list_pending()),
            "processing": len(queue.list_processing()),
            "completed": len(queue.list_completed()),
            "failed": len(queue.list_failed()),
            "recent_results": store.list_results()[:10],
        }
        return HTMLResponse(
            "<!doctype html><html><body style='background:#111;color:#eee;font-family:monospace'>"
            "<h1>Agents</h1>"
            f"<pre>{json.dumps(body, indent=2, default=str)}</pre>"
            "</body></html>"
        )

    @app.get("/logs", response_class=HTMLResponse)
    def logs_page() -> HTMLResponse:
        return HTMLResponse(
            "<!doctype html><html><body style='background:#111;color:#eee;font-family:monospace'>"
            "<button onclick=\"document.getElementById('log-output').textContent=''\">Clear</button>"
            "<pre id='log-output' style='height:90vh;overflow:auto;border:1px solid #444;padding:1rem'></pre>"
            "<script>const es=new EventSource('/logs/stream');es.onmessage=e=>{const pre=document.getElementById('log-output');pre.textContent+=e.data+'\\n';pre.scrollTop=pre.scrollHeight;};</script>"
            "</body></html>"
        )

    @app.get("/logs/stream")
    def stream_logs() -> StreamingResponse:
        def event_stream() -> Any:
            last_size = 0
            while True:
                if RUN_LOG.exists():
                    content = RUN_LOG.read_text(encoding="utf-8")
                    if len(content) > last_size:
                        chunk = content[last_size:]
                        last_size = len(content)
                        for line in chunk.splitlines():
                            if line.strip():
                                yield f"data: {line}\n\n"
                time.sleep(0.5)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.get("/run/{run_id}/export")
    def export_run(run_id: str) -> FileResponse:
        path = RUNS_DIR / f"{run_id}.json"
        if not path.exists():
            raise HTTPException(status_code=404, detail="run not found")
        return FileResponse(path, media_type="application/json", filename=f"{run_id}.json")

    @app.get("/run/{run_id}/export/markdown")
    def export_markdown(run_id: str) -> PlainTextResponse:
        path = RUNS_DIR / f"{run_id}.json"
        payload = _load_json(path, None)
        if not isinstance(payload, dict):
            raise HTTPException(status_code=404, detail="run not found")
        headers = {"Content-Disposition": f"attachment; filename={run_id}.md"}
        return PlainTextResponse(_markdown_report(run_id, payload), media_type="text/markdown", headers=headers)

    @app.get("/health")
    def health() -> JSONResponse:
        return JSONResponse(
            {
                "status": "ok",
                "runs": len(_list_runs()),
                "memory_records": len(_load_json(MEMORY_PATH, [])),
            }
        )
else:  # pragma: no cover - optional dependency surface
    app = None


def dashboard_runtime_error() -> str | None:
    if FASTAPI_IMPORT_ERROR is None:
        return None
    return f"dashboard dependencies unavailable: {FASTAPI_IMPORT_ERROR}"


__all__ = ["app", "cfg", "dashboard_runtime_error"]
