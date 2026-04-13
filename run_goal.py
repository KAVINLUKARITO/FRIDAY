"""
Manual autonomous execution using DeepSeek via Ollama.
"""

from aiworker.autonomy.controller import EvolutionController
from aiworker.autonomy.models import EvolutionConfig
from aiworker.governance.audit import AuditLog
from aiworker.governance.policy import PolicyEngine
from aiworker.governance.circuit_breaker import CircuitBreaker
from aiworker.governance.rate_limiter import RateLimiter
from aiworker.learning.store import LearningStore
from aiworker.llm.deepseek_adapter import DeepSeekAdapter
from aiworker.llm.claude_backend import ClaudeBackend


def main() -> None:
    # -------- CONFIG --------
    config = EvolutionConfig(
      goal="""
      Create a single file:

      aiworker/metrics/__init__.py

      Content:
      \"\"\"Metrics module.\"\"\"

      Rules:
      - Create only this file
      - Do not modify any other file
      - Return valid unified diff
      - Return STRICT JSON ONLY
      """,
       allowed_files=("aiworker/metrics/",),
       max_attempts=3,
       max_lines_changed=20,
   )

    # -------- GOVERNANCE --------
    audit_log = AuditLog()

    policy = PolicyEngine(
        audit_log=audit_log,
        circuit_breaker=CircuitBreaker(),
        rate_limiter=RateLimiter(),
        health_check_enabled=False,
    )

    # -------- PATCH GENERATOR (DeepSeek) --------
    backend = ClaudeBackend()
    patch_generator = DeepSeekAdapter(backend=backend)
 
    # -------- CONTROLLER --------
    controller = EvolutionController(
        config=config,
        policy_engine=policy,
        patch_generator=patch_generator,
        workspace_path=".",   # current repo root
        database=None,        # no DB persistence for now
        audit_log=audit_log,
    )

    result = controller.run()
    print("\n=== ATTEMPT DETAILS ===")

    for attempt in result.attempts:
      print("Attempt:", attempt.attempt_number)
      print("Outcome:", attempt.outcome)
      print("Validation passed:", attempt.validation_passed)
      print("Sandbox success:", attempt.sandbox_success)
      print("Confidence:", attempt.confidence_score)
      print("Detail:", attempt.detail)
      print("Error:", attempt.error)
      print("Patch:", attempt.patch_text)
      print("-" * 40)

    print("\nFINAL RESULT:")
    print(controller.summary(result))


if __name__ == "__main__":
    main()
