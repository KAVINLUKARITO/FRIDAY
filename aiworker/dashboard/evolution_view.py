"""
AIWorker Dashboard Evolution View - Phase 4 Autonomous Intelligence

New dashboard panels for Phase 4 features.

FastAPI routes (add to existing server.py):
- GET /api/meta/strategies - Active strategy recommendations
- GET /api/skills - Skills with mastery levels
- GET /api/goals/queue - Autonomous goal queue
- GET /api/predictions/accuracy - Prediction vs actual data
- GET /api/prompts/variants - Prompt variant stats
- GET /api/schedule - Upcoming scheduled work

Server-Sent Events (lightweight alternative to WebSockets):
- /api/events/stream - Push for state changes
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from aiworker.config import AIWorkerConfig
from aiworker.meta_learning.optimizer import MetaLearningOptimizer, create_meta_optimizer
from aiworker.goals.generator import GoalGenerator, create_goal_generator
from aiworker.memory.skill_store import SkillStore, create_skill_store
from aiworker.predictor.resource_model import ResourcePredictor, create_resource_predictor
from aiworker.evolution.prompt_tuner import PromptTuner, create_prompt_tuner
from aiworker.scheduler.adaptive import AdaptiveScheduler, create_adaptive_scheduler

logger = logging.getLogger("aiworker.dashboard.evolution")

# Create router
router = APIRouter(prefix="/api")

# Global instances (initialized on first use)
_meta_optimizer: Optional[MetaLearningOptimizer] = None
_goal_generator: Optional[GoalGenerator] = None
_skill_store: Optional[SkillStore] = None
_predictor: Optional[ResourcePredictor] = None
_prompt_tuner: Optional[PromptTuner] = None
_scheduler: Optional[AdaptiveScheduler] = None


def get_config():
    """Get AIWorker config."""
    return AIWorkerConfig.from_env()


def get_meta_optimizer():
    """Get or create meta optimizer."""
    global _meta_optimizer
    if _meta_optimizer is None:
        _meta_optimizer = create_meta_optimizer()
    return _meta_optimizer


def get_goal_generator():
    """Get or create goal generator."""
    global _goal_generator
    if _goal_generator is None:
        _goal_generator = create_goal_generator()
    return _goal_generator


def get_skill_store():
    """Get or create skill store."""
    global _skill_store
    if _skill_store is None:
        _skill_store = create_skill_store()
    return _skill_store


def get_predictor():
    """Get or create predictor."""
    global _predictor
    if _predictor is None:
        _predictor = create_resource_predictor()
    return _predictor


def get_prompt_tuner():
    """Get or create prompt tuner."""
    global _prompt_tuner
    if _prompt_tuner is None:
        _prompt_tuner = create_prompt_tuner()
    return _prompt_tuner


def get_scheduler():
    """Get or create scheduler."""
    global _scheduler
    if _scheduler is None:
        _scheduler = create_adaptive_scheduler()
    return _scheduler


# =============================================================================
# Response Models
# =============================================================================

class StrategyResponse(BaseModel):
    """Strategy recommendation response."""
    target: str
    current_value: str
    recommended_value: str
    confidence: float
    rationale: str
    expected_improvement: str
    created_at: float


class SkillResponse(BaseModel):
    """Skill response."""
    name: str
    category: str
    mastery_level: float
    mastery_category: str
    attempts: int
    successes: int
    success_rate: float
    avg_duration_minutes: float
    avg_memory_gb: float
    last_practiced: Optional[float]


class GoalResponse(BaseModel):
    """Autonomous goal response."""
    goal_type: str
    description: str
    target_file: Optional[str]
    rationale: str
    priority_score: float
    expected_outcome: str
    suggested_approach: str
    created_at: float
    status: str


class PredictionAccuracyResponse(BaseModel):
    """Prediction accuracy response."""
    total_predictions: int
    avg_error_percent: Optional[float]
    min_error_percent: Optional[float]
    max_error_percent: Optional[float]
    within_20_percent: bool


class PromptVariantResponse(BaseModel):
    """Prompt variant response."""
    name: str
    usage_count: int
    success_rate: float
    avg_quality: float
    is_active: bool


class ScheduleResponse(BaseModel):
    """Scheduled task response."""
    goal_type: str
    description: str
    target_file: Optional[str]
    priority_score: float
    scheduled_at: float
    predicted_memory_gb: float
    predicted_duration_min: float
    time_window: str
    status: str


# =============================================================================
# API Routes
# =============================================================================

@router.get("/meta/strategies", response_model=list[StrategyResponse])
async def get_strategies():
    """Get active strategy recommendations from meta-learning optimizer."""
    try:
        optimizer = get_meta_optimizer()
        recommendations = optimizer.get_pending_recommendations()
        
        return [
            StrategyResponse(
                target=r.target,
                current_value=str(r.current_value),
                recommended_value=str(r.recommended_value),
                confidence=r.confidence,
                rationale=r.rationale,
                expected_improvement=r.expected_improvement,
                created_at=r.created_at
            )
            for r in recommendations
        ]
    
    except Exception as e:
        logger.error(f"Failed to get strategies: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/skills", response_model=list[SkillResponse])
async def get_skills(
    category: Optional[str] = None,
    min_mastery: float = Query(0.0, ge=0.0, le=1.0)
):
    """Get all skills with mastery levels."""
    try:
        skill_store = get_skill_store()
        skills = skill_store.get_all_skills(category)
        
        # Filter by min mastery
        skills = [s for s in skills if s.mastery_level >= min_mastery]
        
        # Sort by mastery level
        skills.sort(key=lambda s: -s.mastery_level)
        
        return [
            SkillResponse(
                name=s.name,
                category=s.category,
                mastery_level=s.mastery_level,
                mastery_category=s.mastery_category.value,
                attempts=s.attempts,
                successes=s.successes,
                success_rate=s.success_rate,
                avg_duration_minutes=s.avg_duration_minutes,
                avg_memory_gb=s.avg_memory_gb,
                last_practiced=s.last_practiced if s.last_practiced > 0 else None
            )
            for s in skills
        ]
    
    except Exception as e:
        logger.error(f"Failed to get skills: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/skills/summary")
async def get_skills_summary():
    """Get skill summary for dashboard overview."""
    try:
        skill_store = get_skill_store()
        summary = skill_store.get_skill_summary()
        
        return summary
    
    except Exception as e:
        logger.error(f"Failed to get skills summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/goals/queue", response_model=list[GoalResponse])
async def get_goal_queue(
    limit: int = Query(10, ge=1, le=50)
):
    """Get autonomous goal queue with priority scores."""
    try:
        generator = get_goal_generator()
        goals = generator.get_goal_queue(limit)
        
        return [
            GoalResponse(
                goal_type=g.goal_type,
                description=g.description,
                target_file=str(g.target_file) if g.target_file else None,
                rationale=g.rationale,
                priority_score=g.priority_score,
                expected_outcome=g.expected_outcome,
                suggested_approach=g.suggested_approach,
                created_at=g.created_at,
                status=g.status
            )
            for g in goals
        ]
    
    except Exception as e:
        logger.error(f"Failed to get goal queue: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/goals/{goal_type}/bump")
async def bump_goal_priority(goal_type: str, target_file: Optional[str] = None):
    """Bump goal priority (human override)."""
    try:
        generator = get_goal_generator()
        success = generator.bump_priority(goal_type, Path(target_file) if target_file else None)
        
        if not success:
            raise HTTPException(status_code=404, detail="Goal not found")
        
        return {"success": True, "message": f"Priority bumped for {goal_type}"}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to bump goal priority: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/goals/{goal_type}/defer")
async def defer_goal(goal_type: str, target_file: Optional[str] = None):
    """Defer goal to later (human override)."""
    try:
        generator = get_goal_generator()
        success = generator.defer_goal(goal_type, Path(target_file) if target_file else None)
        
        if not success:
            raise HTTPException(status_code=404, detail="Goal not found")
        
        return {"success": True, "message": f"Goal {goal_type} deferred"}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to defer goal: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/predictions/accuracy", response_model=PredictionAccuracyResponse)
async def get_prediction_accuracy(
    days: int = Query(7, ge=1, le=30)
):
    """Get prediction vs actual accuracy data."""
    try:
        predictor = get_predictor()
        stats = predictor.get_accuracy_stats(days)
        
        return PredictionAccuracyResponse(
            total_predictions=stats.get('total_predictions', 0),
            avg_error_percent=stats.get('avg_error_percent'),
            min_error_percent=stats.get('min_error_percent'),
            max_error_percent=stats.get('max_error_percent'),
            within_20_percent=stats.get('within_20_percent', False)
        )
    
    except Exception as e:
        logger.error(f"Failed to get prediction accuracy: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/prompts/variants", response_model=dict[str, list[PromptVariantResponse]])
async def get_prompt_variants():
    """Get active prompt variants with success rates."""
    try:
        tuner = get_prompt_tuner()
        
        result = {}
        for prompt_type in ["code_generation", "research", "planning", "validation"]:
            stats = tuner.get_variant_stats(prompt_type)
            result[prompt_type] = [
                PromptVariantResponse(
                    name=s['name'],
                    usage_count=s['usage_count'],
                    success_rate=s['success_rate'],
                    avg_quality=s['avg_quality'],
                    is_active=s['is_active']
                )
                for s in stats
            ]
        
        return result
    
    except Exception as e:
        logger.error(f"Failed to get prompt variants: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/prompts/timeline")
async def get_prompt_timeline():
    """Get prompt evolution timeline."""
    try:
        tuner = get_prompt_tuner()
        timeline = tuner.get_evolution_timeline()
        
        return {
            "timeline": timeline,
            "total_variants": len(timeline)
        }
    
    except Exception as e:
        logger.error(f"Failed to get prompt timeline: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/schedule", response_model=list[ScheduleResponse])
async def get_schedule(
    limit: int = Query(10, ge=1, le=50)
):
    """Get upcoming scheduled work."""
    try:
        scheduler = get_scheduler()
        tasks = scheduler.get_schedule(limit)
        
        return [
            ScheduleResponse(
                goal_type=t['goal_type'],
                description=t['description'],
                target_file=t['target_file'],
                priority_score=t['priority_score'],
                scheduled_at=t['scheduled_at'],
                predicted_memory_gb=t['predicted_memory_gb'],
                predicted_duration_min=t['predicted_duration_min'],
                time_window=t['time_window'],
                status=t['status']
            )
            for t in tasks
        ]
    
    except Exception as e:
        logger.error(f"Failed to get schedule: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/schedule/stats")
async def get_schedule_stats():
    """Get scheduler statistics."""
    try:
        scheduler = get_scheduler()
        stats = scheduler.get_stats()
        
        return stats
    
    except Exception as e:
        logger.error(f"Failed to get schedule stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Server-Sent Events (lightweight alternative to WebSockets)
# =============================================================================

@router.get("/events/stream")
async def event_stream():
    """
    Server-Sent Events stream for real-time updates.
    
    Sends events on significant changes:
    - goal_completed
    - strategy_updated
    - skill_mastered
    - prompt_promoted
    """
    from fastapi.responses import StreamingResponse
    import asyncio
    
    async def generate_events():
        """Generate SSE events."""
        last_check = time.time()
        
        while True:
            # Check for new events
            # This is a simplified implementation
            # In production, would check databases for changes
            
            # Send heartbeat every 30 seconds
            yield f"data: {{'type': 'heartbeat', 'time': {time.time()}}}\n\n"
            
            await asyncio.sleep(30)
    
    return StreamingResponse(
        generate_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


# =============================================================================
# React Component Descriptions (for frontend reference)
# =============================================================================

REACT_COMPONENTS = {
    "StrategyPanel": {
        "description": "Displays active strategy recommendations with Apply buttons",
        "props": ["strategies", "onApply"],
        "features": [
            "Confidence score visualization",
            "Expected improvement display",
            "One-click apply",
            "Dismiss recommendation"
        ]
    },
    "SkillTree": {
        "description": "Visual mastery progression for all skills",
        "props": ["skills", "onPracticeClick"],
        "features": [
            "Progress bars for mastery levels",
            "Category grouping",
            "Color-coded by mastery (novice=red, competent=yellow, expert=green, master=gold)",
            "Practice button for weak skills"
        ]
    },
    "GoalQueue": {
        "description": "Draggable priority list of autonomous goals",
        "props": ["goals", "onBump", "onDefer", "onDelete"],
        "features": [
            "Priority score display",
            "Drag to reorder",
            "Bump/Defer/Delete actions",
            "Expected outcome preview"
        ]
    },
    "PredictionAccuracyChart": {
        "description": "Line chart of prediction error rates over time",
        "props": ["accuracyData"],
        "features": [
            "Error rate trend line",
            "20% threshold indicator",
            "Time range selector",
            "Improvement indicator"
        ]
    },
    "ScheduleTimeline": {
        "description": "Gantt-style view of upcoming work",
        "props": ["schedule", "predictions"],
        "features": [
            "Time-based layout",
            "Resource usage bars",
            "Time window indicators",
            "Conflict warnings"
        ]
    }
}


# =============================================================================
# Integration with main dashboard server
# =============================================================================

def register_routes(app):
    """Register evolution routes with main FastAPI app."""
    app.include_router(router)
    logger.info("Evolution view routes registered")
