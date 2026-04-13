"""Three-tier safety cage compatibility layer."""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from enum import Enum

from aiworker.config import AIWorkerConfig
from aiworker.pipeline.state import AgentState

logger = logging.getLogger(__name__)


class SafetyTier(str, Enum):
    TIER_1_AUTO = "TIER_1_AUTO"
    TIER_2_HUMAN = "TIER_2_HUMAN"
    TIER_3_KILL = "TIER_3_KILL"


@dataclass
class SafetyResult:
    tier: SafetyTier
    allowed: bool
    reason: str
    patch_hash: str = ""


class SafetyViolation(RuntimeError):
    """Raised when a pipeline state violates runtime safety policy."""


class SafetyCage:
    """Conservative safety gate for generated patches."""

    def __init__(self, step_limit: int | AIWorkerConfig = 20) -> None:
        if isinstance(step_limit, AIWorkerConfig):
            self.config = step_limit
            self.step_limit = step_limit.max_iterations
        else:
            self.config = AIWorkerConfig.from_env()
            self.step_limit = step_limit
        self.max_failures = self.config.max_failures
        self._pending: dict[str, dict] = {}
        self._rejected: set[str] = set()
        self._approved: set[str] = set()
        self._failure_count = 0
        self._consecutive_failures = 0
        self._kill_switch_active = False

    def check(self, state: AgentState) -> None:
        if state.steps_taken >= self.step_limit:
            raise SafetyViolation("step limit exceeded")
        action = state.current_action()
        if action is None:
            return
        text = repr(action).lower()
        forbidden_tokens = ("shell=true", "'shell': true", '"shell": true', "os.system", "eval(", "exec(", "rm -rf", "format c:")
        if any(token in text for token in forbidden_tokens):
            raise SafetyViolation("forbidden operation detected")

    def evaluate(self, patch_content: str) -> SafetyResult:
        patch_hash = hashlib.sha256(patch_content.encode("utf-8", errors="replace")).hexdigest()[:16]
        lowered = patch_content.lower()
        dangerous_tokens = ("rm -rf", "format c:", "subprocess", "os.system", "eval(", "exec(")
        if any(token in lowered for token in dangerous_tokens):
            self._record_failure()
            self._kill_switch_active = self._consecutive_failures >= self.max_failures
            return SafetyResult(
                tier=SafetyTier.TIER_3_KILL,
                allowed=False,
                reason="dangerous token detected",
                patch_hash=patch_hash,
            )

        tier = SafetyTier.TIER_2_HUMAN if not self.config.auto_approve else SafetyTier.TIER_1_AUTO
        self._pending.setdefault(
            patch_hash,
            {
                "patch_hash": patch_hash,
                "target_file": "unknown",
                "rationale": "Generated patch requires review",
                "created_at": time.time(),
                "safety_tier": tier.value,
                "patch_content": patch_content,
            },
        )
        return SafetyResult(tier=tier, allowed=True, reason="requires approval", patch_hash=patch_hash)

    def human_approve(self, patch_content: str, patch_hash: str, rationale: str) -> bool:
        if self.config.auto_approve:
            self._approved.add(patch_hash)
            self._pending.pop(patch_hash, None)
            return True
        self._pending[patch_hash] = {
            "patch_hash": patch_hash,
            "target_file": "unknown",
            "rationale": rationale,
            "created_at": time.time(),
            "safety_tier": SafetyTier.TIER_2_HUMAN.value,
            "patch_content": patch_content,
        }
        return False

    def get_pending_patches(self) -> list[dict]:
        return list(self._pending.values())

    def approve_patch(self, patch_hash: str) -> bool:
        if patch_hash not in self._pending:
            return False
        self._pending.pop(patch_hash, None)
        self._approved.add(patch_hash)
        self._consecutive_failures = 0
        return True

    def reject_patch(self, patch_hash: str, reason: str) -> bool:
        if patch_hash not in self._pending:
            return False
        logger.info("patch %s rejected: %s", patch_hash, reason)
        self._pending.pop(patch_hash, None)
        self._rejected.add(patch_hash)
        self._record_failure()
        return True

    def is_kill_switch_active(self) -> bool:
        return self._kill_switch_active

    def get_failure_count(self) -> int:
        return self._failure_count

    def get_consecutive_failures(self) -> int:
        return self._consecutive_failures

    def reset_kill_switch(self) -> None:
        self._kill_switch_active = False
        self._consecutive_failures = 0

    def _record_failure(self) -> None:
        self._failure_count += 1
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.max_failures:
            self._kill_switch_active = True
