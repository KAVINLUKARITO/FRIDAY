"""
AIWorker Dashboard Server - Phase 2 Integration

Lightweight FastAPI backend for dashboard with:
- Polling-based updates (no WebSockets for 32GB constraint)
- Read-only SQLite queries (no locks on main engine)
- Pagination on all list endpoints (max 20 items)
- Streaming response for logs

Endpoints:
- GET /api/status -> current engine status
- GET /api/config -> sanitized AIWorkerConfig
- GET /api/iterations -> list recent iterations
- GET /api/iterations/{id} -> full iteration details
- GET /api/patches/pending -> patches awaiting approval
- POST /api/patches/{hash}/approve -> non-interactive approval
- POST /api/patches/{hash}/reject -> reject with reason
- GET /api/safety/status -> kill switch status
- POST /api/safety/reset -> reset kill switch
- GET /api/logs -> tail of aiworker.log

Static files: dashboard/build mounted at /
"""

import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import AsyncGenerator, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Import AIWorker components
from aiworker.config import AIWorkerConfig
from aiworker.engine.sequential_engine import SequentialEngine
from aiworker.safety.safety_cage import SafetyCage

# Configure logging
logger = logging.getLogger("aiworker.dashboard")

# Create FastAPI app
app = FastAPI(
    title="AIWorker Dashboard API",
    description="Lightweight API for AIWorker monitoring and control",
    version="2.0.0"
)


def create_app() -> FastAPI:
    return app


def start_dashboard_server(host: str = "127.0.0.1", port: int = 8000) -> None:
    import uvicorn

    uvicorn.run(app, host=host, port=port, reload=False, log_level="info")


def get_metrics_payload() -> dict:
    return {
        "cpu": 0.0,
        "memory": 0.0,
        "ai_confidence": 0.0,
        "requests_per_min": 0,
        "errors_24h": 0,
        "patch_success_rate": 0.0,
        "loop_state": "idle",
        "skills": {},
        "learning_progress": 0.0,
        "research_progress": 0.0,
        "loop_iterations": 0,
        "tasks_completed": 0,
        "tasks_failed": 0,
        "agent_activity": [],
        "current_stage": "IDLE",
        "loop_pipeline": [],
        "patch_lifecycle": [],
        "runtime_status": "idle",
        "runtime_iteration": 0,
        "active_goal": "",
        "last_action": "",
    }


def get_skills_payload() -> dict:
    return {"skills": {}}


def get_patches_payload() -> list[dict]:
    return []


def get_policy_payload() -> dict:
    return {"read_only": True, "admin_mode": False, "auto_apply": False}


def get_runtime_payload() -> dict:
    return {"running": False, "iteration": 0}


def get_loop_state_payload() -> dict:
    return {"loop_state": "idle"}


def get_system_status_payload() -> dict:
    return {"autonomy_loop_active": False, "current_stage": "IDLE"}


def get_debug_stream_payload() -> list[dict]:
    return []

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global config
_config: Optional[AIWorkerConfig] = None


def get_config() -> AIWorkerConfig:
    """Get or load AIWorker configuration."""
    global _config
    if _config is None:
        _config = AIWorkerConfig.from_env()
    return _config


def get_db_connection() -> sqlite3.Connection:
    """Get read-only database connection."""
    config = get_config()
    db_path = config.checkpoint_db
    
    # Connect with read-only mode for dashboard queries
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


# =============================================================================
# Response Models
# =============================================================================

class StatusResponse(BaseModel):
    """Engine status response."""
    state: str
    iteration_id: Optional[str]
    started_at: Optional[float]
    duration_seconds: Optional[float]
    error_count: int
    memory_usage: dict
    pending_approvals: int


class ConfigResponse(BaseModel):
    """Sanitized configuration response."""
    base_path: str
    max_iterations: int
    checkpoint_db: str
    ollama_host: str
    ollama_model: str
    auto_approve: bool


class IterationSummary(BaseModel):
    """Summary of an iteration."""
    id: str
    state: str
    goal: str
    started_at: float
    completed_at: Optional[float]
    success: Optional[bool]


class IterationDetail(BaseModel):
    """Full iteration details."""
    id: str
    state: str
    goal: str
    started_at: float
    completed_at: Optional[float]
    success: Optional[bool]
    error_count: int
    data: dict


class PatchPending(BaseModel):
    """Pending patch for approval."""
    patch_hash: str
    target_file: str
    rationale: str
    created_at: float
    safety_tier: str


class SafetyStatus(BaseModel):
    """Safety system status."""
    kill_switch_active: bool
    failure_count: int
    consecutive_failures: int
    max_failures: int


class ApprovalRequest(BaseModel):
    """Patch approval request."""
    admin_key: Optional[str] = None


class RejectionRequest(BaseModel):
    """Patch rejection request."""
    reason: str
    admin_key: Optional[str] = None


# =============================================================================
# API Endpoints
# =============================================================================

@app.get("/api/status", response_model=StatusResponse)
async def get_status():
    """Get current engine status from SequentialEngine."""
    try:
        config = get_config()
        
        # Create temporary engine to check status
        engine = SequentialEngine(db_path=config.checkpoint_db)
        
        # Get current iteration if any
        current = engine.get_current_iteration()
        
        # Get memory usage
        import psutil
        mem = psutil.virtual_memory()
        
        # Get pending approvals (from safety cage)
        safety_cage = SafetyCage(config)
        pending = len(safety_cage.get_pending_patches())
        
        return StatusResponse(
            state=current.get('state', 'IDLE') if current else 'IDLE',
            iteration_id=current.get('iteration_id') if current else None,
            started_at=current.get('started_at') if current else None,
            duration_seconds=current.get('duration_seconds') if current else None,
            error_count=current.get('error_count', 0) if current else 0,
            memory_usage={
                "used_gb": round(mem.used / (1024 ** 3), 2),
                "total_gb": round(mem.total / (1024 ** 3), 2),
                "percent": mem.percent
            },
            pending_approvals=pending
        )
    
    except Exception as e:
        logger.error(f"Status check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/config", response_model=ConfigResponse)
async def get_config_endpoint():
    """Get sanitized AIWorkerConfig."""
    try:
        config = get_config()
        
        return ConfigResponse(
            base_path=config.base_path,
            max_iterations=config.max_iterations,
            checkpoint_db=config.checkpoint_db,
            ollama_host=config.ollama_host,
            ollama_model=config.ollama_model,
            auto_approve=config.auto_approve
        )
    
    except Exception as e:
        logger.error(f"Config retrieval failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/iterations", response_model=list[IterationSummary])
async def list_iterations(
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0)
):
    """List recent iterations from SQLite (paginated)."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT iteration_id, state, goal, started_at, completed_at, success
            FROM iterations
            ORDER BY started_at DESC
            LIMIT ? OFFSET ?
        ''', (limit, offset))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [
            IterationSummary(
                id=row['iteration_id'],
                state=row['state'],
                goal=row['goal'][:100] if row['goal'] else '',
                started_at=row['started_at'],
                completed_at=row['completed_at'],
                success=row['success']
            )
            for row in rows
        ]
    
    except Exception as e:
        logger.error(f"Iterations list failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/iterations/{iteration_id}", response_model=IterationDetail)
async def get_iteration(iteration_id: str):
    """Get full iteration details."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM iterations WHERE iteration_id = ?
        ''', (iteration_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            raise HTTPException(status_code=404, detail="Iteration not found")
        
        # Parse data JSON
        try:
            data = json.loads(row['data']) if row['data'] else {}
        except json.JSONDecodeError:
            data = {}
        
        return IterationDetail(
            id=row['iteration_id'],
            state=row['state'],
            goal=row['goal'],
            started_at=row['started_at'],
            completed_at=row['completed_at'],
            success=row['success'],
            error_count=row['error_count'],
            data=data
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Iteration retrieval failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/patches/pending", response_model=list[PatchPending])
async def get_pending_patches():
    """List patches awaiting human approval."""
    try:
        config = get_config()
        safety_cage = SafetyCage(config)
        
        pending = safety_cage.get_pending_patches()
        
        return [
            PatchPending(
                patch_hash=p['patch_hash'],
                target_file=p.get('target_file', 'unknown'),
                rationale=p.get('rationale', '')[:200],
                created_at=p.get('created_at', 0),
                safety_tier=p.get('safety_tier', 'TIER_2_HUMAN')
            )
            for p in pending
        ]
    
    except Exception as e:
        logger.error(f"Pending patches retrieval failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/patches/{patch_hash}/approve")
async def approve_patch(patch_hash: str, request: ApprovalRequest):
    """Non-interactive approval for web UI."""
    try:
        config = get_config()
        safety_cage = SafetyCage(config)
        
        # Verify admin key if configured
        admin_key = os.environ.get('AIWORKER_ADMIN_KEY')
        if admin_key and request.admin_key != admin_key:
            raise HTTPException(status_code=403, detail="Invalid admin key")
        
        success = safety_cage.approve_patch(patch_hash)
        
        if not success:
            raise HTTPException(status_code=404, detail="Patch not found or already processed")
        
        return {"success": True, "message": f"Patch {patch_hash} approved"}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Patch approval failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/patches/{patch_hash}/reject")
async def reject_patch(patch_hash: str, request: RejectionRequest):
    """Reject patch with reason."""
    try:
        config = get_config()
        safety_cage = SafetyCage(config)
        
        # Verify admin key if configured
        admin_key = os.environ.get('AIWORKER_ADMIN_KEY')
        if admin_key and request.admin_key != admin_key:
            raise HTTPException(status_code=403, detail="Invalid admin key")
        
        success = safety_cage.reject_patch(patch_hash, request.reason)
        
        if not success:
            raise HTTPException(status_code=404, detail="Patch not found or already processed")
        
        return {"success": True, "message": f"Patch {patch_hash} rejected"}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Patch rejection failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/safety/status", response_model=SafetyStatus)
async def get_safety_status():
    """Get kill switch status and failure counts."""
    try:
        config = get_config()
        safety_cage = SafetyCage(config)
        
        return SafetyStatus(
            kill_switch_active=safety_cage.is_kill_switch_active(),
            failure_count=safety_cage.get_failure_count(),
            consecutive_failures=safety_cage.get_consecutive_failures(),
            max_failures=safety_cage.max_failures
        )
    
    except Exception as e:
        logger.error(f"Safety status retrieval failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/safety/reset")
async def reset_kill_switch(request: ApprovalRequest):
    """Reset kill switch (requires admin key)."""
    try:
        config = get_config()
        
        # Verify admin key
        admin_key = os.environ.get('AIWORKER_ADMIN_KEY')
        if not admin_key:
            raise HTTPException(status_code=403, detail="Admin key not configured")
        
        if request.admin_key != admin_key:
            raise HTTPException(status_code=403, detail="Invalid admin key")
        
        safety_cage = SafetyCage(config)
        safety_cage.reset_kill_switch()
        
        return {"success": True, "message": "Kill switch reset"}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Kill switch reset failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def log_streamer(log_path: Path, lines: int = 100) -> AsyncGenerator[str, None]:
    """Stream log file content."""
    try:
        if not log_path.exists():
            yield "Log file not found\n"
            return
        
        # Read last N lines
        with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
            all_lines = f.readlines()
            last_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines
        
        for line in last_lines:
            yield line
    
    except Exception as e:
        yield f"Error reading log: {e}\n"


@app.get("/api/logs")
async def get_logs(lines: int = Query(100, ge=1, le=1000)):
    """Get tail of aiworker.log (streaming response)."""
    try:
        config = get_config()
        log_path = Path(config.base_path) / "logs" / "aiworker.log"
        
        return StreamingResponse(
            log_streamer(log_path, lines),
            media_type="text/plain"
        )
    
    except Exception as e:
        logger.error(f"Log retrieval failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Static Files (React Frontend)
# =============================================================================

# Mount dashboard build at root
static_path = Path(__file__).parent / "build"
if static_path.exists():
    app.mount("/static", StaticFiles(directory=str(static_path / "static")), name="static")


@app.get("/{full_path:path}")
async def serve_spa(full_path: str, request: Request):
    """Serve index.html for all non-API routes (SPA behavior)."""
    # Skip API routes
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found")
    
    index_path = static_path / "index.html"
    
    if index_path.exists():
        return FileResponse(str(index_path))
    else:
        # Return API info if no frontend built
        return {
            "message": "AIWorker Dashboard API",
            "version": "2.0.0",
            "docs": "/docs",
            "endpoints": [
                "/api/status",
                "/api/config",
                "/api/iterations",
                "/api/patches/pending",
                "/api/safety/status",
                "/api/logs"
            ]
        }


# =============================================================================
# Startup Event
# =============================================================================

@app.on_event("startup")
async def startup_event():
    """Initialize on startup."""
    logger.info("Dashboard server starting")
    
    # Ensure directories exist
    config = get_config()
    Path(config.base_path).mkdir(parents=True, exist_ok=True)
    Path(config.base_path, "logs").mkdir(parents=True, exist_ok=True)
    Path(config.base_path, "data").mkdir(parents=True, exist_ok=True)


# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    
    config = get_config()
    
    uvicorn.run(
        "aiworker.dashboard.server:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info"
    )
