<!-- ARCHIVED: moved from repo root. Not a source file. -->

# Architectural Review & Milestone 10 PR

## Architectural Review of `aiworker`

### Module Inventory (8 modules, ~1,270 source lines)

| Module | Lines | Purpose | External Deps |
|--------|-------|---------|---------------|
| advisory | 113 | LLM advisory via HTTP | urllib (stdlib) |
| execution | 267 | Sandbox isolation, patching, test runner | subprocess (stdlib) |
| memory | 207 | SQLite persistence for change history | sqlite3 (stdlib) |
| monitor | 139 | System status via psutil | psutil |
| orchestration | 90 | Task queue and analytical pipeline | — |
| planning | 134 | Rule-based plan generation & simulation | — |
| scoring | 90 | Confidence calculation from history | — |
| self_modify | 229 | Change request validation, approval gate, engine | — |

### Dependency Graph

```
advisory (isolated — no inbound consumers)
monitor  (isolated — no inbound consumers)

planning ──> planning.models
             │
orchestration ──> planning.planner
             │   planning.simulator
             │   scoring.decision_context
             │   memory.database
             │
scoring ──> memory.database
            scoring.metrics
            │
self_modify ──> execution.runner
                memory.database
                memory.repository
                scoring.decision_context
                self_modify.change_request
                self_modify.patch_validator
                self_modify.approval
```

**Coupling hub**: `memory.Database` is imported by 7 modules — acceptable for a shared persistence layer but worth monitoring.

### Strengths

1. **Immutability discipline**: Every data model is a frozen dataclass with `to_dict()` — no mutation bugs possible.
2. **Safety invariants**: No auto-approval anywhere. `explicit_approval` flag required. Workspace never modified by engine.
3. **Determinism**: Planning, simulation, and scoring produce identical output for identical input — fully testable.
4. **Layered architecture**: Clear separation between analysis (planning → simulation → scoring) and execution (sandbox → patcher → runner).
5. **Parameterised SQL**: All database queries use `?` placeholders — SQL injection hardened.

### Critical Gaps for Production

1. **No governance layer** — The system has no circuit breaker, rate limiter, or audit trail. A self-modifying AI that can execute unlimited failing attempts is a safety risk.

2. **Disconnected modules** — `advisory` and `monitor` are implemented but never consumed by any pipeline. The orchestrator produces analytical reports but doesn't feed into the engine.

3. **No structured observability** — Only `sandbox.py` uses Python logging. No audit events, no tracing, no way to answer "what happened and why" after the fact.

4. **Engine has zero error handling** — `self_modify/engine.py` contains no try/except blocks. Any unexpected exception propagates unguarded to the caller.

5. **No configuration management** — Thresholds, timeouts, and endpoints are scattered as module-level constants. No unified config mechanism.

### Prioritised Roadmap

| Priority | Milestone | Rationale |
|----------|-----------|-----------|
| **P0** | **Governance & Audit Trail** | Safety-critical: must exist before any production deployment |
| P1 | Pipeline Integration | Wire orchestrator → engine → advisory into end-to-end flow |
| P2 | Configuration Layer | Centralise all constants into a typed config object |
| P3 | Structured Logging | Replace ad-hoc logging with event-driven observability |
| P4 | Diff Generation | The missing "brain" — generate patches from goals via LLM |

---

## PR: `feature/governance-audit` → `main`

### Summary

Adds `aiworker/governance/` — a production governance layer that gates every change attempt through safety checks before it enters the self-modification pipeline.

### New Files (7 files, +1,464 lines)

**`aiworker/governance/audit.py`** (181 lines)
- `AuditEvent` frozen dataclass: event_id, timestamp, category, severity, action, detail, metadata, attempt_id
- `create_event()` factory with auto-generated UUID and UTC timestamp
- `AuditLog` append-only store with filtering: by_category, by_severity, by_attempt, last_n, errors_and_critical

**`aiworker/governance/circuit_breaker.py`** (188 lines)
- Three-state machine: `closed` → `open` → `half_open` → `closed`
- Configurable `failure_threshold` (trips after N consecutive failures) and `recovery_after` (ticks before probe)
- `CircuitStatus` frozen dataclass with `can_proceed` flag
- `record_success()`, `record_failure()`, `tick()`, `reset()` methods

**`aiworker/governance/rate_limiter.py`** (147 lines)
- Sliding-window algorithm with configurable `max_attempts` and `window_seconds`
- Injectable clock for deterministic testing (no flaky time-dependent tests)
- `check()` (read-only) vs `acquire()` (consumes slot) separation
- `RateLimitStatus` frozen dataclass with `seconds_until_available`

**`aiworker/governance/policy.py`** (241 lines)
- `PolicyEngine` combines circuit breaker + rate limiter + optional health check
- `evaluate()` runs all checks, emits audit events, returns `PolicyDecision`
- `record_outcome()` updates breaker/limiter after attempt completion
- Health check integrates with `aiworker.monitor.status` (fails open if unavailable)

**`aiworker/tests/test_governance.py`** (689 lines)
- 47 test cases across 14 test classes
- Covers: immutability, state machine transitions, sliding window math, combined policy evaluation, audit trail completeness, health-gated execution, no side effects

### Design Decisions

| Decision | Rationale |
|----------|-----------|
| Fail-open on health check errors | A broken monitor shouldn't block the entire pipeline |
| Injectable clock in RateLimiter | Enables deterministic tests without sleep() |
| Separate `check()` vs `acquire()` | Policy evaluation shouldn't consume rate-limit slots |
| `record_outcome()` as explicit call | Engine controls when to update governance state |
| No database persistence (yet) | Audit events are in-memory; DB persistence is a follow-up |
| All statuses are frozen dataclasses | Consistent with project conventions |

### Testing

All 47 test cases pass. Tests use no network, no filesystem writes, and no external dependencies beyond the existing codebase.

### Integration Points

The governance module is designed to wrap the existing `process_change_request()` call:

```python
# Before (no governance):
result = process_change_request(cr, patch, ws)

# After (governed):
decision = policy_engine.evaluate(attempt_id="...")
if not decision.allowed:
    return decision.reasons  # blocked by governance

result = process_change_request(cr, patch, ws)
policy_engine.record_outcome(success=result.approved, attempt_id="...")
```

Wiring this into `engine.py` is deferred to the Pipeline Integration milestone (P1).
