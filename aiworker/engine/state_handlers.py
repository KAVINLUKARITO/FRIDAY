"""
AIWorker State Handlers - Phase 2 Integration

Six state handlers for SequentialEngine, wired to self_modify engine and research layer:
- handle_plan: Parse goal and determine strategy
- handle_research: Gather external knowledge
- handle_code: Generate patch candidates
- handle_validate: Safety checks and regression tests
- handle_apply: Human approval and patch application
- handle_learn: Record metrics and update skill store

Each handler takes IterationContext, returns new State.
"""

import logging
import time
import traceback
from pathlib import Path
from typing import Callable

from pydantic import BaseModel

# Import from Phase 1 and 2 components
from aiworker.engine.sequential_engine import IterationContext, State
from aiworker.self_modify.engine import SelfModifyEngine, PatchCandidate
from aiworker.safety.safety_cage import SafetyCage, SafetyTier

# Configure logging
logger = logging.getLogger("aiworker.state_handlers")


class HandlerResult(BaseModel):
    """Result of state handler execution."""
    next_state: State
    success: bool
    message: str = ""
    error: str = ""


class StateHandlers:
    """
    Container for all state handlers with shared dependencies.
    
    Handlers are wired to:
    - SelfModifyEngine for patch generation and application
    - SafetyCage for three-tier safety system
    - WebResearcher for external knowledge gathering
    """
    
    def __init__(
        self,
        self_modify_engine: SelfModifyEngine,
        safety_cage: SafetyCage,
        web_researcher=None  # Optional, from Phase 1
    ):
        self.self_modify = self_modify_engine
        self.safety_cage = safety_cage
        self.web_researcher = web_researcher
        
        # Handler registry
        self._handlers: dict[State, Callable[[IterationContext], State]] = {
            State.PLAN: self.handle_plan,
            State.RESEARCH: self.handle_research,
            State.CODE: self.handle_code,
            State.VALIDATE: self.handle_validate,
            State.APPLY: self.handle_apply,
            State.LEARN: self.handle_learn,
        }
        
        logger.info("StateHandlers initialized")
    
    def get_handler(self, state: State) -> Callable[[IterationContext], State]:
        """Get handler for a given state."""
        return self._handlers.get(state, self._handle_unknown)
    
    def _handle_unknown(self, context: IterationContext) -> State:
        """Handle unknown states."""
        logger.error(f"Unknown state: {context.state}")
        context.error_count += 1
        return State.ERROR
    
    def _log_progress(self, context: IterationContext, message: str):
        """Log progress for dashboard visibility."""
        elapsed = time.time() - context.started_at
        logger.info(
            f"[{context.iteration_id}] {context.state.value} | "
            f"{elapsed:.1f}s | {message}"
        )
    
    def _handle_error(self, context: IterationContext, error: Exception) -> State:
        """Handle exceptions in state handlers."""
        context.error_count += 1
        error_msg = f"{type(error).__name__}: {str(error)}"
        context.data['last_error'] = error_msg
        context.data['error_traceback'] = traceback.format_exc()
        
        logger.error(f"Handler error: {error_msg}")
        
        # Check for max errors
        if context.error_count >= 3:
            logger.error("Max errors reached, transitioning to ERROR state")
            return State.ERROR
        
        # Retry current state
        return context.state
    
    # =====================================================================
    # Handler 1: PLAN
    # =====================================================================
    
    def handle_plan(self, context: IterationContext) -> State:
        """
        Parse goal and determine improvement strategy.
        
        - Parse goal from context.goal
        - Use research.web_researcher if external knowledge needed
        - Determine target file and improvement strategy
        - Store plan in context.data['plan']
        - Return State.RESEARCH if research needed, else State.CODE
        """
        try:
            self._log_progress(context, "Planning improvement strategy")
            
            goal = context.goal
            if not goal:
                raise ValueError("No goal specified in context")
            
            # Use self_modify engine to plan the change
            rationale = self.self_modify.plan_change(goal, context)
            
            # Get plan from context (set by plan_change)
            plan = context.data.get('plan', {})
            
            # Determine if research is needed
            topic = plan.get('topic')
            
            if topic and self.web_researcher:
                self._log_progress(context, f"Research needed for topic: {topic[:50]}...")
                return State.RESEARCH
            
            self._log_progress(context, f"Plan created for: {plan.get('target_file')}")
            return State.CODE
        
        except Exception as e:
            return self._handle_error(context, e)
    
    # =====================================================================
    # Handler 2: RESEARCH
    # =====================================================================
    
    def handle_research(self, context: IterationContext) -> State:
        """
        Gather external knowledge for the improvement.
        
        - Call web_researcher.collect_knowledge() for topic
        - Store findings in context.data['research_findings']
        - Return State.CODE
        """
        try:
            self._log_progress(context, "Gathering external knowledge")
            
            plan = context.data.get('plan', {})
            topic = plan.get('topic')
            
            if not topic:
                logger.warning("No research topic in plan, skipping research")
                context.data['research_findings'] = {}
                return State.CODE
            
            if not self.web_researcher:
                logger.warning("No web_researcher available, skipping research")
                context.data['research_findings'] = {
                    'error': 'Web researcher not available',
                    'topic': topic
                }
                return State.CODE
            
            # Call web researcher
            findings = self.web_researcher.collect_knowledge(topic)
            
            context.data['research_findings'] = {
                'topic': topic,
                'findings': findings,
                'timestamp': time.time()
            }
            
            self._log_progress(
                context, 
                f"Research complete: {len(findings) if isinstance(findings, list) else 'N/A'} items"
            )
            return State.CODE
        
        except Exception as e:
            # Research failure is non-fatal, continue to CODE
            logger.warning(f"Research failed: {e}, continuing without research")
            context.data['research_findings'] = {
                'error': str(e),
                'topic': context.data.get('plan', {}).get('topic')
            }
            return State.CODE
    
    # =====================================================================
    # Handler 3: CODE
    # =====================================================================
    
    def handle_code(self, context: IterationContext) -> State:
        """
        Generate patch candidate.
        
        - Call self_modify.engine.generate_patch() with plan and research
        - Store PatchCandidate in context.data['patch_candidate']
        - Return State.VALIDATE
        """
        try:
            self._log_progress(context, "Generating patch candidate")
            
            plan = context.data.get('plan', {})
            target_file = plan.get('target_file')
            rationale = plan.get('rationale', '')
            
            if not target_file:
                raise ValueError("No target file specified in plan")
            
            target_path = Path(target_file)
            if not target_path.is_absolute():
                target_path = Path("/opt/aiworker") / target_path
            
            # Generate patch
            candidate = self.self_modify.generate_patch(
                target_file=target_path,
                rationale=rationale,
                context=context
            )
            
            # Store in context
            context.data['patch_candidate'] = candidate.model_dump()
            
            self._log_progress(
                context, 
                f"Patch generated: {candidate.patch_hash} for {target_file}"
            )
            return State.VALIDATE
        
        except Exception as e:
            return self._handle_error(context, e)
    
    # =====================================================================
    # Handler 4: VALIDATE
    # =====================================================================
    
    def handle_validate(self, context: IterationContext) -> State:
        """
        Validate patch candidate.
        
        - Get candidate from context.data['patch_candidate']
        - Run safety_cage.evaluate() (Tier 1 - automatic)
        - If passes: run self_modify.engine.validate_patch() (regression tests)
        - Store validation result in context.data['validation']
        - Return State.APPLY if valid, State.CODE if needs fix, State.ERROR if fatal
        """
        try:
            self._log_progress(context, "Validating patch candidate")
            
            candidate_data = context.data.get('patch_candidate')
            if not candidate_data:
                raise ValueError("No patch candidate in context")
            
            candidate = PatchCandidate(**candidate_data)
            
            # Tier 1: SafetyCage automatic evaluation
            self._log_progress(context, "Running Tier 1 safety evaluation")
            safety_result = self.safety_cage.evaluate(candidate.patched_content)
            
            # Store safety result
            candidate.safety_result = safety_result
            context.data['patch_candidate'] = candidate.model_dump()
            
            if safety_result.tier == SafetyTier.TIER_3_KILL:
                # Kill switch triggered - fatal
                logger.error(f"Kill switch triggered: {safety_result.reason}")
                context.data['validation'] = {
                    'passed': False,
                    'fatal': True,
                    'error': f"Kill switch: {safety_result.reason}"
                }
                return State.ERROR
            
            if safety_result.tier == SafetyTier.TIER_2_HUMAN:
                # Needs human approval - this is expected, continue to APPLY
                logger.info(f"Patch requires human approval: {safety_result.reason}")
            
            # Run regression tests via self_modify engine
            self._log_progress(context, "Running regression tests")
            tests_passed = self.self_modify.validate_patch(candidate, context)
            
            validation_result = context.data.get('validation', {})
            validation_result['tests_passed'] = tests_passed
            validation_result['safety_tier'] = safety_result.tier.value
            
            context.data['validation'] = validation_result
            
            if tests_passed:
                self._log_progress(context, "Validation passed")
                return State.APPLY
            else:
                # Tests failed - try to fix
                errors = validation_result.get('errors', [])
                logger.warning(f"Validation failed: {errors}")
                
                # Increment error count
                context.error_count += 1
                
                if context.error_count >= 3:
                    return State.ERROR
                
                # Try to regenerate patch
                self._log_progress(context, "Attempting patch regeneration")
                return State.CODE
        
        except Exception as e:
            return self._handle_error(context, e)
    
    # =====================================================================
    # Handler 5: APPLY
    # =====================================================================
    
    def handle_apply(self, context: IterationContext) -> State:
        """
        Apply validated patch with human approval.
        
        - Get candidate from context.data['patch_candidate']
        - Run safety_cage.human_approve() (Tier 2 - BLOCKING for input)
        - If approved: self_modify.engine.apply_patch()
        - Return State.LEARN if success, State.ERROR if fail
        """
        try:
            self._log_progress(context, "Awaiting human approval")
            
            candidate_data = context.data.get('patch_candidate')
            if not candidate_data:
                raise ValueError("No patch candidate in context")
            
            candidate = PatchCandidate(**candidate_data)
            
            # Tier 2: Human approval (BLOCKING)
            approved = self.safety_cage.human_approve(
                patch_content=candidate.patched_content,
                patch_hash=candidate.patch_hash,
                rationale=candidate.rationale
            )
            
            if not approved:
                logger.info("Patch rejected by human")
                context.data['apply_result'] = {
                    'success': False,
                    'reason': 'human_rejected'
                }
                # Not a fatal error, just skip this iteration
                return State.IDLE
            
            self._log_progress(context, "Human approved, applying patch")
            
            # Apply the patch
            success = self.self_modify.apply_patch(candidate, context)
            
            if success:
                self._log_progress(context, "Patch applied successfully")
                return State.LEARN
            else:
                logger.error("Patch application failed")
                context.error_count += 1
                
                if context.error_count >= 3:
                    return State.ERROR
                
                # Try to rollback and retry
                self.self_modify.rollback_patch(candidate)
                return State.CODE
        
        except Exception as e:
            return self._handle_error(context, e)
    
    # =====================================================================
    # Handler 6: LEARN
    # =====================================================================
    
    def handle_learn(self, context: IterationContext) -> State:
        """
        Record success/failure and update skill store.
        
        - Record success/failure metrics
        - Update skill store (SQLite)
        - Return State.IDLE
        """
        try:
            self._log_progress(context, "Recording learning metrics")
            
            # Get apply result
            apply_result = context.data.get('apply_result', {})
            success = apply_result.get('success', False)
            
            # Build metrics
            metrics = {
                'iteration_id': context.iteration_id,
                'success': success,
                'duration_seconds': time.time() - context.started_at,
                'error_count': context.error_count,
                'target_file': context.data.get('plan', {}).get('target_file'),
                'patch_hash': apply_result.get('patch_hash'),
                'commit_hash': apply_result.get('commit_hash'),
                'timestamp': time.time()
            }
            
            context.data['metrics'] = metrics
            
            # Update skill store (SQLite)
            self._update_skill_store(context, metrics)
            
            self._log_progress(context, f"Learning complete: success={success}")
            return State.IDLE
        
        except Exception as e:
            # Learning failure is non-fatal
            logger.warning(f"Learning recording failed: {e}")
            return State.IDLE
    
    def _update_skill_store(self, context: IterationContext, metrics: dict):
        """Update skill store with iteration metrics."""
        try:
            import sqlite3
            
            db_path = Path("/opt/aiworker/data/skills.db")
            db_path.parent.mkdir(parents=True, exist_ok=True)
            
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            
            # Create table if not exists
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS iterations (
                    id TEXT PRIMARY KEY,
                    success BOOLEAN,
                    duration_seconds REAL,
                    error_count INTEGER,
                    target_file TEXT,
                    patch_hash TEXT,
                    commit_hash TEXT,
                    timestamp REAL,
                    goal TEXT,
                    data TEXT
                )
            ''')
            
            # Insert metrics
            cursor.execute('''
                INSERT OR REPLACE INTO iterations 
                (id, success, duration_seconds, error_count, target_file, 
                 patch_hash, commit_hash, timestamp, goal, data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                metrics['iteration_id'],
                metrics['success'],
                metrics['duration_seconds'],
                metrics['error_count'],
                metrics.get('target_file'),
                metrics.get('patch_hash'),
                metrics.get('commit_hash'),
                metrics['timestamp'],
                context.goal,
                str(context.data)
            ))
            
            conn.commit()
            conn.close()
            
            logger.debug(f"Skill store updated for {context.iteration_id}")
        
        except Exception as e:
            logger.warning(f"Failed to update skill store: {e}")


# =============================================================================
# Factory function
# =============================================================================

def create_state_handlers(
    self_modify_engine: SelfModifyEngine,
    safety_cage: SafetyCage,
    web_researcher=None
) -> StateHandlers:
    """Create StateHandlers with all dependencies."""
    return StateHandlers(
        self_modify_engine=self_modify_engine,
        safety_cage=safety_cage,
        web_researcher=web_researcher
    )
