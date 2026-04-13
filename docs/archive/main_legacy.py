"""
AIWorker Main Entry Point - Phase 2 Integration

Primary entry point using SequentialEngine with:
- CLI commands: run, resume, status, approve, self-improve
- Signal handlers for graceful shutdown
- Ollama health check
- Memory monitoring (32GB constraint)
- Cron-compatible non-interactive mode

Usage:
    python -m aiworker.main run "Optimize SQLite queries"
    python -m aiworker.main resume
    python -m aiworker.main status
"""

import argparse
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Optional

import psutil

# Import Phase 1 and 2 components
from aiworker.config import AIWorkerConfig
from aiworker.engine.sequential_engine import SequentialEngine, IterationContext, State
from aiworker.engine.state_handlers import create_state_handlers, StateHandlers
from aiworker.self_modify.engine import create_self_modify_engine, SelfModifyEngine
from aiworker.safety.safety_cage import SafetyCage
from aiworker.research.web_researcher import WebResearcher  # Phase 1

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/opt/aiworker/logs/aiworker.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("aiworker.main")

# Global state for signal handling
_engine: Optional[SequentialEngine] = None
_shutdown_requested = False


def load_config() -> AIWorkerConfig:
    """Load AIWorker configuration from environment."""
    logger.info("Loading configuration")
    config = AIWorkerConfig.from_env()
    
    # Ensure required directories exist
    Path(config.base_path).mkdir(parents=True, exist_ok=True)
    Path(config.base_path, "logs").mkdir(parents=True, exist_ok=True)
    Path(config.base_path, "data").mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Configuration loaded: base_path={config.base_path}")
    return config


def check_ollama_health(config: AIWorkerConfig) -> bool:
    """Check if Ollama is accessible."""
    import httpx
    
    try:
        response = httpx.get(
            f"{config.ollama_host}/api/tags",
            timeout=10.0
        )
        if response.status_code == 200:
            models = response.json().get('models', [])
            logger.info(f"Ollama healthy: {len(models)} models available")
            return True
        else:
            logger.warning(f"Ollama returned status {response.status_code}")
            return False
    except Exception as e:
        logger.warning(f"Ollama health check failed: {e}")
        return False


def check_memory_usage() -> dict:
    """Check current memory usage."""
    mem = psutil.virtual_memory()
    
    # Convert to GB
    total_gb = mem.total / (1024 ** 3)
    used_gb = mem.used / (1024 ** 3)
    available_gb = mem.available / (1024 ** 3)
    percent = mem.percent
    
    result = {
        "total_gb": round(total_gb, 2),
        "used_gb": round(used_gb, 2),
        "available_gb": round(available_gb, 2),
        "percent": percent,
        "warning": used_gb > 28  # 32GB system, warn at 28GB
    }
    
    if result["warning"]:
        logger.warning(f"High memory usage: {used_gb:.1f}GB / {total_gb:.1f}GB ({percent}%)")
    
    return result


def init_engine(config: AIWorkerConfig) -> SequentialEngine:
    """Initialize SequentialEngine with all handlers registered."""
    logger.info("Initializing SequentialEngine")
    
    # Create safety cage
    safety_cage = SafetyCage(config)
    
    # Create self-modify engine
    self_modify = create_self_modify_engine(safety_cage, config.base_path)
    
    # Create web researcher (Phase 1)
    try:
        web_researcher = WebResearcher(config)
        logger.info("WebResearcher initialized")
    except Exception as e:
        logger.warning(f"WebResearcher initialization failed: {e}")
        web_researcher = None
    
    # Create state handlers
    handlers = create_state_handlers(self_modify, safety_cage, web_researcher)
    
    # Create and configure engine
    engine = SequentialEngine(
        db_path=config.checkpoint_db,
        max_iterations=config.max_iterations
    )
    
    # Register all handlers
    for state in [State.PLAN, State.RESEARCH, State.CODE, State.VALIDATE, State.APPLY, State.LEARN]:
        engine.register_handler(state, handlers.get_handler(state))
    
    logger.info("SequentialEngine initialized with all handlers")
    return engine


def run_iteration(goal: str, config: AIWorkerConfig) -> bool:
    """
    Run a single autonomy iteration.
    
    Args:
        goal: The improvement goal
        config: AIWorker configuration
        
    Returns:
        True if iteration completed successfully
    """
    global _engine
    
    logger.info(f"Starting iteration with goal: {goal[:50]}...")
    
    # Check memory before starting
    mem = check_memory_usage()
    if mem["warning"]:
        logger.error("Memory too high, cannot start iteration")
        return False
    
    # Initialize engine
    _engine = init_engine(config)
    
    # Start iteration
    try:
        context = _engine.start_iteration(goal)
        
        # Run to completion
        while context.state not in [State.IDLE, State.ERROR, State.PAUSED]:
            if _shutdown_requested:
                logger.info("Shutdown requested, pausing iteration")
                _engine.pause_iteration()
                return False
            
            # Check memory periodically
            mem = check_memory_usage()
            if mem["warning"]:
                logger.warning("Memory warning during iteration")
            
            # Step the engine
            context = _engine.step()
            
            # Small delay to prevent tight loop
            time.sleep(0.1)
        
        success = context.state == State.IDLE
        logger.info(f"Iteration completed: success={success}")
        return success
    
    except Exception as e:
        logger.error(f"Iteration failed: {e}")
        return False


def resume_or_start(config: AIWorkerConfig) -> str:
    """
    Handle crash recovery - resume from checkpoint or start fresh.
    
    Returns:
        Message about action taken
    """
    logger.info("Checking for recoverable iterations")
    
    # Create temporary engine to check checkpoints
    temp_engine = SequentialEngine(db_path=config.checkpoint_db)
    
    # Check for incomplete iterations
    incomplete = temp_engine.get_incomplete_iterations()
    
    if incomplete:
        iteration_id = incomplete[0]
        logger.info(f"Found incomplete iteration: {iteration_id}")
        return f"Resuming iteration: {iteration_id}"
    else:
        logger.info("No incomplete iterations found")
        return "No iterations to resume"


def get_status(config: AIWorkerConfig) -> dict:
    """Get current engine status."""
    temp_engine = SequentialEngine(db_path=config.checkpoint_db)
    
    # Get recent iterations
    recent = temp_engine.get_recent_iterations(limit=5)
    
    # Get incomplete iterations
    incomplete = temp_engine.get_incomplete_iterations()
    
    # Memory status
    mem = check_memory_usage()
    
    return {
        "recent_iterations": recent,
        "incomplete_iterations": incomplete,
        "memory": mem,
        "timestamp": time.time()
    }


def approve_patch(patch_hash: str, config: AIWorkerConfig) -> bool:
    """
    Non-interactive approval for dashboard use.
    
    Args:
        patch_hash: Hash of patch to approve
        config: AIWorker configuration
        
    Returns:
        True if approved
    """
    safety_cage = SafetyCage(config)
    
    # This would typically retrieve the pending patch and approve it
    # For now, just log the request
    logger.info(f"Approval requested for patch: {patch_hash}")
    
    # In a real implementation, this would interact with the safety cage
    # to approve a pending patch without interactive prompts
    
    return True


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global _shutdown_requested
    
    sig_name = signal.Signals(signum).name
    logger.info(f"Received signal {sig_name}, initiating graceful shutdown")
    
    _shutdown_requested = True
    
    if _engine:
        _engine.pause_iteration()
    
    # Give time for checkpoint to be saved
    time.sleep(1)
    
    logger.info("Shutdown complete")
    sys.exit(0)


def main():
    """Main CLI entry point."""
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Parse arguments
    parser = argparse.ArgumentParser(
        description="AIWorker 2.0 - Self-Improving AI Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m aiworker.main run "Optimize SQLite queries in memory module"
  python -m aiworker.main resume
  python -m aiworker.main status
  python -m aiworker.main approve abc123def456
  python -m aiworker.main self-improve
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # run command
    run_parser = subparsers.add_parser('run', help='Run single iteration with goal')
    run_parser.add_argument('goal', nargs='+', help='Improvement goal')
    run_parser.add_argument('--non-interactive', '-n', action='store_true',
                          help='Non-interactive mode (cron-compatible)')
    
    # resume command
    subparsers.add_parser('resume', help='Resume from last checkpoint')
    
    # status command
    subparsers.add_parser('status', help='Print current engine status')
    
    # approve command
    approve_parser = subparsers.add_parser('approve', help='Non-interactive patch approval')
    approve_parser.add_argument('patch_hash', help='Hash of patch to approve')
    
    # self-improve command
    subparsers.add_parser('self-improve', help='Start default self-improvement goal')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    # Load configuration
    config = load_config()
    
    # Check Ollama health (non-blocking warning)
    if not check_ollama_health(config):
        logger.warning("Ollama not available, some features may be limited")
    
    # Execute command
    if args.command == 'run':
        goal = ' '.join(args.goal)
        success = run_iteration(goal, config)
        sys.exit(0 if success else 1)
    
    elif args.command == 'resume':
        result = resume_or_start(config)
        print(result)
        
        # Actually resume if there's something to resume
        if "Resuming" in result:
            # TODO: Implement actual resume logic
            logger.info("Resume functionality would continue iteration here")
        
        sys.exit(0)
    
    elif args.command == 'status':
        status = get_status(config)
        
        print("\n" + "=" * 50)
        print("AIWorker Status")
        print("=" * 50)
        print(f"Memory: {status['memory']['used_gb']:.1f}GB / {status['memory']['total_gb']:.1f}GB")
        print(f"Recent Iterations: {len(status['recent_iterations'])}")
        print(f"Incomplete Iterations: {len(status['incomplete_iterations'])}")
        
        if status['incomplete_iterations']:
            print(f"\nIncomplete: {status['incomplete_iterations'][0]}")
        
        print("=" * 50 + "\n")
        sys.exit(0)
    
    elif args.command == 'approve':
        success = approve_patch(args.patch_hash, config)
        print(f"Approval {'successful' if success else 'failed'}")
        sys.exit(0 if success else 1)
    
    elif args.command == 'self-improve':
        # Default self-improvement goal
        goal = "Improve error handling and add logging to core modules"
        print(f"Starting self-improvement: {goal}")
        success = run_iteration(goal, config)
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
