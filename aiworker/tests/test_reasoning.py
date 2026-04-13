"""Tests for the reasoning package and DeepSeek adapter.

Covers:
- Module mapper: import extraction, path conversion, BFS traversal
- Context assembler: file reading, truncation, token estimation
- Reasoning planner: plan construction, risk scoring, hypothesis building
- DeepSeek adapter: strict JSON validation, prompt building, retry logic
- StubBackend determinism
- ReasoningPlan immutability and validation
- DeepSeekResponse immutability

Uses unittest only — no pytest dependency.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import textwrap
import unittest

from aiworker.debugger.capture import FailureReport
from aiworker.debugger.root_cause import RootCauseResult
from aiworker.reasoning.module_mapper import (
    ModuleNode,
    _extract_imports_from_source,
    affected_module_paths,
    map_dependencies,
)
from aiworker.reasoning.context_assembler import (
    AssembledContext,
    FileContext,
    assemble_context,
)
from aiworker.reasoning.planner import (
    ReasoningPlan,
    create_plan,
)
from aiworker.llm.deepseek_adapter import (
    RepairAdapter,
    DeepSeekResponse,
    StubBackend,
    _validate_response,
    _build_prompt,
)


# ── Helpers ──────────────────────────────────────────────────


def _make_report(
    exception_type: str = "ValueError",
    message: str = "test error",
    traceback: str = "",
    failing_tests: tuple[str, ...] = (),
    affected_files: tuple[str, ...] = (),
) -> FailureReport:
    return FailureReport(
        exception_type=exception_type,
        message=message,
        traceback=traceback,
        failing_tests=failing_tests,
        affected_files=affected_files,
    )


def _make_root_cause(
    resolved: bool = False,
    category: str = "unknown",
    explanation: str = "Could not determine",
    suggested_fix: str | None = None,
) -> RootCauseResult:
    return RootCauseResult(
        resolved=resolved,
        category=category,
        explanation=explanation,
        suggested_fix=suggested_fix,
    )


def _valid_json_response(
    analysis: str = "Found the bug",
    diff: str = "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-bad\n+good",
    risk_score: float = 0.3,
) -> str:
    return json.dumps({
        "analysis": analysis,
        "diff": diff,
        "risk_score": risk_score,
    })


# ── Module mapper ────────────────────────────────────────────


class TestImportExtraction(unittest.TestCase):
    """Verify AST-based import extraction."""

    def test_extracts_aiworker_imports(self) -> None:
        source = textwrap.dedent("""\
            import aiworker.governance.policy
            from aiworker.learning.store import LearningStore
            import os
        """)
        imports = _extract_imports_from_source(source)
        self.assertIn("aiworker.governance.policy", imports)
        self.assertIn("aiworker.learning.store", imports)
        self.assertNotIn("os", imports)

    def test_empty_source(self) -> None:
        self.assertEqual(_extract_imports_from_source(""), [])

    def test_syntax_error_returns_empty(self) -> None:
        self.assertEqual(_extract_imports_from_source("def !!!"), [])

    def test_deduplicates(self) -> None:
        source = textwrap.dedent("""\
            from aiworker.foo import bar
            from aiworker.foo import baz
        """)
        imports = _extract_imports_from_source(source)
        self.assertEqual(imports.count("aiworker.foo"), 1)


class TestAffectedModulePaths(unittest.TestCase):
    """Verify file path to module path conversion."""

    def test_basic_conversion(self) -> None:
        paths = affected_module_paths(
            ["aiworker/governance/policy.py"],
            repo_root="/repo",
        )
        self.assertIn("aiworker.governance.policy", paths)

    def test_init_file(self) -> None:
        paths = affected_module_paths(
            ["aiworker/governance/__init__.py"],
            repo_root="/repo",
        )
        self.assertIn("aiworker.governance", paths)

    def test_non_py_excluded(self) -> None:
        paths = affected_module_paths(
            ["aiworker/README.md"],
            repo_root="/repo",
        )
        self.assertEqual(paths, ())

    def test_sorted_output(self) -> None:
        paths = affected_module_paths(
            ["aiworker/z.py", "aiworker/a.py"],
            repo_root="/repo",
        )
        self.assertEqual(paths, tuple(sorted(paths)))


class TestModuleNode(unittest.TestCase):
    """Verify ModuleNode immutability."""

    def test_frozen(self) -> None:
        node = ModuleNode(
            module_path="aiworker.foo",
            file_path="/repo/aiworker/foo.py",
            imports=(),
            depth=0,
        )
        with self.assertRaises(AttributeError):
            node.depth = 1

    def test_to_dict(self) -> None:
        node = ModuleNode(
            module_path="aiworker.foo",
            file_path="/repo/aiworker/foo.py",
            imports=("aiworker.bar",),
            depth=0,
        )
        d = node.to_dict()
        self.assertEqual(d["module_path"], "aiworker.foo")
        self.assertIsInstance(d["imports"], list)


class TestMapDependencies(unittest.TestCase):
    """Verify dependency graph traversal with real files."""

    def test_with_temp_repo(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            # Create a mini aiworker structure
            pkg = os.path.join(td, "aiworker")
            os.makedirs(pkg)
            with open(os.path.join(pkg, "__init__.py"), "w") as f:
                f.write("")
            with open(os.path.join(pkg, "foo.py"), "w") as f:
                f.write("from aiworker.bar import something\n")
            with open(os.path.join(pkg, "bar.py"), "w") as f:
                f.write("x = 1\n")

            nodes = map_dependencies(
                root_modules=["aiworker.foo"],
                repo_root=td,
                max_depth=2,
            )
            paths = [n.module_path for n in nodes]
            self.assertIn("aiworker.foo", paths)
            self.assertIn("aiworker.bar", paths)

    def test_nonexistent_module(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            nodes = map_dependencies(
                root_modules=["aiworker.nonexistent"],
                repo_root=td,
                max_depth=1,
            )
            self.assertEqual(len(nodes), 1)
            self.assertEqual(nodes[0].file_path, "")

    def test_respects_max_depth(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            pkg = os.path.join(td, "aiworker")
            os.makedirs(pkg)
            with open(os.path.join(pkg, "__init__.py"), "w") as f:
                f.write("")
            with open(os.path.join(pkg, "a.py"), "w") as f:
                f.write("from aiworker.b import x\n")
            with open(os.path.join(pkg, "b.py"), "w") as f:
                f.write("from aiworker.c import y\n")
            with open(os.path.join(pkg, "c.py"), "w") as f:
                f.write("y = 1\n")

            nodes = map_dependencies(
                root_modules=["aiworker.a"],
                repo_root=td,
                max_depth=1,
            )
            paths = [n.module_path for n in nodes]
            self.assertIn("aiworker.a", paths)
            self.assertIn("aiworker.b", paths)
            # c should not be reached at depth=1
            self.assertNotIn("aiworker.c", paths)


# ── Context assembler ────────────────────────────────────────


class TestFileContext(unittest.TestCase):
    """Verify FileContext immutability."""

    def test_frozen(self) -> None:
        fc = FileContext(
            file_path="foo.py",
            module_path="aiworker.foo",
            content="x = 1",
            line_count=1,
            truncated=False,
        )
        with self.assertRaises(AttributeError):
            fc.content = "changed"


class TestAssembleContext(unittest.TestCase):
    """Verify context assembly from module nodes."""

    def test_assembles_from_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            pkg = os.path.join(td, "aiworker")
            os.makedirs(pkg)
            with open(os.path.join(pkg, "foo.py"), "w") as f:
                f.write("def foo():\n    return 1\n")

            nodes = (
                ModuleNode(
                    module_path="aiworker.foo",
                    file_path=os.path.join(pkg, "foo.py"),
                    imports=(),
                    depth=0,
                ),
            )
            ctx = assemble_context(nodes, td)
            self.assertEqual(len(ctx.files), 1)
            self.assertIn("def foo", ctx.files[0].content)
            self.assertGreater(ctx.total_tokens_estimate, 0)

    def test_empty_nodes(self) -> None:
        ctx = assemble_context((), "/tmp")
        self.assertEqual(len(ctx.files), 0)
        self.assertEqual(ctx.total_tokens_estimate, 0)

    def test_respects_max_total_chars(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            pkg = os.path.join(td, "aiworker")
            os.makedirs(pkg)
            for name in ("a", "b"):
                with open(os.path.join(pkg, f"{name}.py"), "w") as f:
                    f.write("x = 1\n" * 100)

            nodes = tuple(
                ModuleNode(
                    module_path=f"aiworker.{name}",
                    file_path=os.path.join(pkg, f"{name}.py"),
                    imports=(),
                    depth=0,
                )
                for name in ("a", "b")
            )
            ctx = assemble_context(nodes, td, max_total_chars=50)
            total = sum(len(f.content) for f in ctx.files)
            self.assertLessEqual(total, 50)

    def test_to_dict(self) -> None:
        ctx = AssembledContext(
            files=(), total_tokens_estimate=0, summary="empty"
        )
        d = ctx.to_dict()
        self.assertIn("files", d)
        self.assertIn("summary", d)


# ── Reasoning planner ────────────────────────────────────────


class TestReasoningPlan(unittest.TestCase):
    """Verify ReasoningPlan validation and immutability."""

    def test_valid_construction(self) -> None:
        plan = ReasoningPlan(
            hypothesis="Bug in module X",
            affected_modules=("aiworker.foo",),
            risk_score=0.5,
            strategy="Fix the import",
        )
        self.assertEqual(plan.hypothesis, "Bug in module X")

    def test_frozen(self) -> None:
        plan = ReasoningPlan(
            hypothesis="test",
            affected_modules=(),
            risk_score=0.5,
            strategy="test",
        )
        with self.assertRaises(AttributeError):
            plan.risk_score = 0.9

    def test_empty_hypothesis_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ReasoningPlan(
                hypothesis="",
                affected_modules=(),
                risk_score=0.5,
                strategy="test",
            )

    def test_risk_score_out_of_range_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ReasoningPlan(
                hypothesis="test",
                affected_modules=(),
                risk_score=1.5,
                strategy="test",
            )

    def test_empty_strategy_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ReasoningPlan(
                hypothesis="test",
                affected_modules=(),
                risk_score=0.5,
                strategy="",
            )

    def test_to_dict(self) -> None:
        plan = ReasoningPlan(
            hypothesis="test",
            affected_modules=("aiworker.foo",),
            risk_score=0.5,
            strategy="fix it",
            failure_type="ValueError",
            failing_tests=("test_a",),
        )
        d = plan.to_dict()
        self.assertIn("hypothesis", d)
        self.assertIsInstance(d["affected_modules"], list)
        self.assertIsInstance(d["failing_tests"], list)


class TestCreatePlan(unittest.TestCase):
    """Verify plan creation from failure context."""

    def test_creates_plan_from_report(self) -> None:
        report = _make_report(
            exception_type="ImportError",
            message="No module named 'foo'",
        )
        root = _make_root_cause(resolved=False)
        plan = create_plan(report, root)
        self.assertIn("ImportError", plan.hypothesis)
        self.assertGreater(plan.risk_score, 0.0)
        self.assertLessEqual(plan.risk_score, 1.0)

    def test_risk_score_higher_for_unknown(self) -> None:
        report = _make_report()
        unknown = _make_root_cause(category="unknown")
        structural = _make_root_cause(category="structural")
        plan_unknown = create_plan(report, unknown)
        plan_struct = create_plan(report, structural)
        self.assertGreater(plan_unknown.risk_score, plan_struct.risk_score)

    def test_with_repo_root(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            pkg = os.path.join(td, "aiworker")
            os.makedirs(pkg)
            fpath = os.path.join(pkg, "test_mod.py")
            with open(fpath, "w") as f:
                f.write("x = 1\n")
            with open(os.path.join(pkg, "__init__.py"), "w") as f:
                f.write("")

            report = _make_report(affected_files=(fpath,))
            root = _make_root_cause()
            plan = create_plan(report, root, repo_root=td)
            self.assertGreater(len(plan.affected_modules), 0)


# ── DeepSeek response validation ─────────────────────────────


class TestResponseValidation(unittest.TestCase):
    """Verify strict JSON validation of LLM output."""

    def test_valid_json(self) -> None:
        resp = _validate_response(_valid_json_response())
        self.assertTrue(resp.valid)
        self.assertEqual(resp.analysis, "Found the bug")
        self.assertGreater(len(resp.diff), 0)
        self.assertAlmostEqual(resp.risk_score, 0.3)

    def test_empty_response(self) -> None:
        resp = _validate_response("")
        self.assertFalse(resp.valid)
        self.assertGreater(len(resp.errors), 0)

    def test_not_json(self) -> None:
        resp = _validate_response("I found the bug and here is the fix...")
        self.assertFalse(resp.valid)
        self.assertTrue(any("not valid JSON" in e for e in resp.errors))

    def test_missing_keys(self) -> None:
        resp = _validate_response(json.dumps({"analysis": "yes"}))
        self.assertFalse(resp.valid)
        self.assertTrue(any("Missing required" in e for e in resp.errors))

    def test_risk_score_out_of_range(self) -> None:
        resp = _validate_response(json.dumps({
            "analysis": "x",
            "diff": "--- a\n+++ b\n@@ -1 +1 @@\n-a\n+b",
            "risk_score": 1.5,
        }))
        self.assertFalse(resp.valid)
        self.assertTrue(any("risk_score" in e for e in resp.errors))

    def test_risk_score_negative(self) -> None:
        resp = _validate_response(json.dumps({
            "analysis": "x",
            "diff": "--- a\n+++ b\n@@ -1 +1 @@\n-a\n+b",
            "risk_score": -0.1,
        }))
        self.assertFalse(resp.valid)

    def test_empty_diff(self) -> None:
        resp = _validate_response(json.dumps({
            "analysis": "x",
            "diff": "",
            "risk_score": 0.3,
        }))
        self.assertFalse(resp.valid)
        self.assertTrue(any("diff" in e for e in resp.errors))

    def test_risk_score_not_number(self) -> None:
        resp = _validate_response(json.dumps({
            "analysis": "x",
            "diff": "some diff",
            "risk_score": "high",
        }))
        self.assertFalse(resp.valid)

    def test_non_object_json(self) -> None:
        resp = _validate_response(json.dumps([1, 2, 3]))
        self.assertFalse(resp.valid)
        self.assertTrue(any("not a JSON object" in e for e in resp.errors))

    def test_risk_score_boundary(self) -> None:
        for score in (0.0, 1.0):
            resp = _validate_response(json.dumps({
                "analysis": "x",
                "diff": "--- a\n+++ b\n@@ -1 +1 @@\n-a\n+b",
                "risk_score": score,
            }))
            self.assertTrue(resp.valid, f"score={score} should be valid")


class TestDeepSeekResponse(unittest.TestCase):
    """Verify DeepSeekResponse immutability."""

    def test_frozen(self) -> None:
        resp = DeepSeekResponse(valid=True, analysis="x", diff="d", risk_score=0.5)
        with self.assertRaises(AttributeError):
            resp.valid = False

    def test_to_dict(self) -> None:
        resp = DeepSeekResponse(
            valid=False, errors=("err1", "err2")
        )
        d = resp.to_dict()
        self.assertIn("valid", d)
        self.assertIsInstance(d["errors"], list)


# ── DeepSeek adapter ─────────────────────────────────────────


class TestStubBackend(unittest.TestCase):
    """Verify StubBackend determinism."""

    def test_returns_fixed_response(self) -> None:
        backend = StubBackend(_valid_json_response())
        self.assertEqual(backend.generate("any prompt"), _valid_json_response())

    def test_tracks_calls(self) -> None:
        backend = StubBackend("x")
        backend.generate("a")
        backend.generate("b")
        self.assertEqual(backend.call_count, 2)

    def test_stores_last_prompt(self) -> None:
        backend = StubBackend("x")
        backend.generate("hello world")
        self.assertEqual(backend.last_prompt, "hello world")


class TestRepairAdapter(unittest.TestCase):
    """Verify adapter orchestration."""

    def _make_plan(self) -> ReasoningPlan:
        return ReasoningPlan(
            hypothesis="Bug in module X",
            affected_modules=("aiworker.foo",),
            risk_score=0.5,
            strategy="Fix the import",
            failure_type="ImportError",
        )

    def test_valid_response(self) -> None:
        backend = StubBackend(_valid_json_response())
        adapter = RepairAdapter(backend=backend)
        resp = adapter.generate(self._make_plan())
        self.assertTrue(resp.valid)
        self.assertEqual(resp.analysis, "Found the bug")

    def test_invalid_response(self) -> None:
        backend = StubBackend("not json at all")
        adapter = RepairAdapter(backend=backend)
        resp = adapter.generate(self._make_plan())
        self.assertFalse(resp.valid)

    def test_retry_logic(self) -> None:
        backend = StubBackend("invalid")
        adapter = RepairAdapter(backend=backend, max_retries=3)
        resp = adapter.generate(self._make_plan())
        self.assertFalse(resp.valid)
        self.assertEqual(adapter.total_calls, 3)

    def test_max_retries_validation(self) -> None:
        with self.assertRaises(ValueError):
            RepairAdapter(backend=StubBackend("x"), max_retries=0)

    def test_total_calls_tracked(self) -> None:
        backend = StubBackend(_valid_json_response())
        adapter = RepairAdapter(backend=backend)
        adapter.generate(self._make_plan())
        adapter.generate(self._make_plan())
        self.assertEqual(adapter.total_calls, 2)


class TestPromptBuilding(unittest.TestCase):
    """Verify prompt construction."""

    def test_prompt_contains_plan_info(self) -> None:
        plan = ReasoningPlan(
            hypothesis="Missing import in foo",
            affected_modules=("aiworker.foo",),
            risk_score=0.4,
            strategy="Add the import statement",
            failure_type="ImportError",
            failing_tests=("test_foo::test_bar",),
        )
        prompt = _build_prompt(plan)
        self.assertIn("ImportError", prompt)
        self.assertIn("Missing import", prompt)
        self.assertIn("aiworker.foo", prompt)
        self.assertIn("test_foo::test_bar", prompt)
        self.assertIn("JSON", prompt)

    def test_prompt_instructs_json_only(self) -> None:
        plan = ReasoningPlan(
            hypothesis="test",
            affected_modules=(),
            risk_score=0.3,
            strategy="test",
        )
        prompt = _build_prompt(plan)
        self.assertIn("ONLY", prompt)
        self.assertIn("JSON", prompt)


# ── DeepSeekAdapter (PatchGenerator) ─────────────────────────


from unittest.mock import patch as mock_patch, MagicMock
from aiworker.llm.deepseek_adapter import (
    DeepSeekAdapter,
    _build_patch_prompt,
    _format_plan_steps,
    _validate_diff_output,
)
from aiworker.planning.models import Plan, PlanStep


_VALID_DIFF_OUTPUT = (
    "diff --git a/foo.py b/foo.py\n"
    "--- a/foo.py\n"
    "+++ b/foo.py\n"
    "@@ -1,2 +1,3 @@\n"
    " def foo():\n"
    "     return 1\n"
    "+    # fixed\n"
)


class TestDeepSeekAdapterConstruction(unittest.TestCase):
    """Verify DeepSeekAdapter parameter validation."""

    def test_default_construction(self) -> None:
        adapter = DeepSeekAdapter()
        self.assertEqual(adapter.model_name, "deepseek-coder:7b")
        self.assertAlmostEqual(adapter.temperature, 0.2)
        self.assertEqual(adapter.max_tokens, 2048)
        self.assertEqual(adapter.timeout, 180)

    def test_custom_parameters(self) -> None:
        adapter = DeepSeekAdapter(
            model_name="codellama:13b",
            temperature=0.0,
            max_tokens=4096,
            timeout=300,
        )
        self.assertEqual(adapter.model_name, "codellama:13b")
        self.assertAlmostEqual(adapter.temperature, 0.0)
        self.assertEqual(adapter.max_tokens, 4096)
        self.assertEqual(adapter.timeout, 300)

    def test_empty_model_name_rejected(self) -> None:
        with self.assertRaises(ValueError):
            DeepSeekAdapter(model_name="")

    def test_whitespace_model_name_rejected(self) -> None:
        with self.assertRaises(ValueError):
            DeepSeekAdapter(model_name="   ")

    def test_negative_temperature_rejected(self) -> None:
        with self.assertRaises(ValueError):
            DeepSeekAdapter(temperature=-0.1)

    def test_temperature_above_two_rejected(self) -> None:
        with self.assertRaises(ValueError):
            DeepSeekAdapter(temperature=2.1)

    def test_zero_max_tokens_rejected(self) -> None:
        with self.assertRaises(ValueError):
            DeepSeekAdapter(max_tokens=0)

    def test_zero_timeout_rejected(self) -> None:
        with self.assertRaises(ValueError):
            DeepSeekAdapter(timeout=0)

    def test_temperature_boundary_zero(self) -> None:
        adapter = DeepSeekAdapter(temperature=0.0)
        self.assertAlmostEqual(adapter.temperature, 0.0)

    def test_temperature_boundary_two(self) -> None:
        adapter = DeepSeekAdapter(temperature=2.0)
        self.assertAlmostEqual(adapter.temperature, 2.0)


class TestBuildPatchPrompt(unittest.TestCase):
    """Verify deterministic patch prompt construction."""

    def test_contains_goal(self) -> None:
        prompt = _build_patch_prompt(
            goal="Add multiply function",
            allowed_files=("math_utils.py",),
            plan_steps="1. Add function",
            temperature=0.2,
            seed=None,
        )
        self.assertIn("Add multiply function", prompt)

    def test_contains_allowed_files(self) -> None:
        prompt = _build_patch_prompt(
            goal="test",
            allowed_files=("a.py", "b.py"),
            plan_steps="steps",
            temperature=0.2,
            seed=None,
        )
        self.assertIn("a.py", prompt)
        self.assertIn("b.py", prompt)

    def test_contains_temperature(self) -> None:
        prompt = _build_patch_prompt(
            goal="test",
            allowed_files=("a.py",),
            plan_steps="steps",
            temperature=0.5,
            seed=None,
        )
        self.assertIn("temperature 0.5", prompt)

    def test_contains_seed_when_provided(self) -> None:
        prompt = _build_patch_prompt(
            goal="test",
            allowed_files=("a.py",),
            plan_steps="steps",
            temperature=0.2,
            seed=42,
        )
        self.assertIn("seed 42", prompt)

    def test_no_seed_when_none(self) -> None:
        prompt = _build_patch_prompt(
            goal="test",
            allowed_files=("a.py",),
            plan_steps="steps",
            temperature=0.2,
            seed=None,
        )
        self.assertNotIn("seed", prompt.lower().split("reproducibility")[0]
                         if "reproducibility" in prompt.lower() else prompt)

    def test_contains_diff_instructions(self) -> None:
        prompt = _build_patch_prompt(
            goal="test",
            allowed_files=("a.py",),
            plan_steps="steps",
            temperature=0.2,
            seed=None,
        )
        self.assertIn("unified diff", prompt)
        self.assertIn("No markdown", prompt)
        self.assertIn("No backticks", prompt)
        self.assertIn("diff --git", prompt)

    def test_deterministic(self) -> None:
        args = dict(
            goal="test goal",
            allowed_files=("a.py", "b.py"),
            plan_steps="do the thing",
            temperature=0.2,
            seed=42,
        )
        p1 = _build_patch_prompt(**args)
        p2 = _build_patch_prompt(**args)
        self.assertEqual(p1, p2)

    def test_empty_allowed_files(self) -> None:
        prompt = _build_patch_prompt(
            goal="test",
            allowed_files=(),
            plan_steps="steps",
            temperature=0.2,
            seed=None,
        )
        self.assertIn("(any)", prompt)


class TestFormatPlanSteps(unittest.TestCase):
    """Verify Plan step formatting."""

    def test_empty_steps(self) -> None:
        plan = Plan(goal="Add feature", steps=(), complexity_score=0.5)
        result = _format_plan_steps(plan)
        self.assertIn("Add feature", result)
        self.assertIn("0.5", result)

    def test_with_steps(self) -> None:
        steps = (
            PlanStep(step_id=1, description="Add function", estimated_risk="low", requires_tests=True),
            PlanStep(step_id=2, description="Add tests", estimated_risk="low", requires_tests=False),
        )
        plan = Plan(goal="Improve code", steps=steps, complexity_score=0.3)
        result = _format_plan_steps(plan)
        self.assertIn("1. Add function", result)
        self.assertIn("2. Add tests", result)
        self.assertIn("[risk=low]", result)


class TestValidateDiffOutput(unittest.TestCase):
    """Verify raw output validation for unified diffs."""

    def test_valid_diff_accepted(self) -> None:
        result = _validate_diff_output(_VALID_DIFF_OUTPUT)
        self.assertIsNotNone(result)
        self.assertTrue(result.startswith("diff --git"))

    def test_empty_string_rejected(self) -> None:
        self.assertIsNone(_validate_diff_output(""))

    def test_whitespace_only_rejected(self) -> None:
        self.assertIsNone(_validate_diff_output("   \n\n  "))

    def test_none_input_rejected(self) -> None:
        self.assertIsNone(_validate_diff_output(None))

    def test_backticks_rejected(self) -> None:
        output = "```diff\n" + _VALID_DIFF_OUTPUT + "\n```"
        self.assertIsNone(_validate_diff_output(output))

    def test_triple_backtick_anywhere_rejected(self) -> None:
        output = _VALID_DIFF_OUTPUT + "\n```\n"
        self.assertIsNone(_validate_diff_output(output))

    def test_no_diff_header_rejected(self) -> None:
        output = "Here is the fix:\n--- a/foo.py\n+++ b/foo.py\n"
        self.assertIsNone(_validate_diff_output(output))

    def test_natural_language_rejected(self) -> None:
        output = "I found the bug and here is how to fix it..."
        self.assertIsNone(_validate_diff_output(output))

    def test_strips_leading_whitespace(self) -> None:
        output = "\n\n" + _VALID_DIFF_OUTPUT
        result = _validate_diff_output(output)
        self.assertIsNotNone(result)
        self.assertTrue(result.startswith("diff --git"))

    def test_deterministic(self) -> None:
        r1 = _validate_diff_output(_VALID_DIFF_OUTPUT)
        r2 = _validate_diff_output(_VALID_DIFF_OUTPUT)
        self.assertEqual(r1, r2)


class TestDeepSeekAdapterGenerate(unittest.TestCase):
    """Verify generate() with mocked subprocess."""

    def _make_plan(self) -> Plan:
        return Plan(goal="Add multiply function", steps=(), complexity_score=0.3)

    def _mock_subprocess_result(
        self, stdout: str = "", returncode: int = 0
    ) -> MagicMock:
        mock_result = MagicMock()
        mock_result.stdout = stdout
        mock_result.returncode = returncode
        return mock_result

    @mock_patch("aiworker.llm.deepseek_adapter.subprocess.run")
    def test_valid_diff_returned(self, mock_run: MagicMock) -> None:
        mock_run.return_value = self._mock_subprocess_result(
            stdout=_VALID_DIFF_OUTPUT
        )
        adapter = DeepSeekAdapter()
        result = adapter.generate(
            self._make_plan(), "Add multiply", ("math_utils.py",)
        )
        self.assertIsNotNone(result)
        self.assertTrue(result.startswith("diff --git"))

    @mock_patch("aiworker.llm.deepseek_adapter.subprocess.run")
    def test_backtick_output_returns_none(self, mock_run: MagicMock) -> None:
        mock_run.return_value = self._mock_subprocess_result(
            stdout="```diff\n" + _VALID_DIFF_OUTPUT + "\n```"
        )
        adapter = DeepSeekAdapter()
        result = adapter.generate(
            self._make_plan(), "test", ("a.py",)
        )
        self.assertIsNone(result)

    @mock_patch("aiworker.llm.deepseek_adapter.subprocess.run")
    def test_non_diff_output_returns_none(self, mock_run: MagicMock) -> None:
        mock_run.return_value = self._mock_subprocess_result(
            stdout="I think the problem is in foo.py..."
        )
        adapter = DeepSeekAdapter()
        result = adapter.generate(
            self._make_plan(), "test", ("a.py",)
        )
        self.assertIsNone(result)

    @mock_patch("aiworker.llm.deepseek_adapter.subprocess.run")
    def test_empty_output_returns_none(self, mock_run: MagicMock) -> None:
        mock_run.return_value = self._mock_subprocess_result(stdout="")
        adapter = DeepSeekAdapter()
        result = adapter.generate(
            self._make_plan(), "test", ("a.py",)
        )
        self.assertIsNone(result)

    @mock_patch("aiworker.llm.deepseek_adapter.subprocess.run")
    def test_nonzero_exit_returns_none(self, mock_run: MagicMock) -> None:
        mock_run.return_value = self._mock_subprocess_result(
            stdout=_VALID_DIFF_OUTPUT, returncode=1
        )
        adapter = DeepSeekAdapter()
        result = adapter.generate(
            self._make_plan(), "test", ("a.py",)
        )
        self.assertIsNone(result)

    @mock_patch("aiworker.llm.deepseek_adapter.subprocess.run")
    def test_timeout_returns_none(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd=["ollama"], timeout=180
        )
        adapter = DeepSeekAdapter()
        result = adapter.generate(
            self._make_plan(), "test", ("a.py",)
        )
        self.assertIsNone(result)

    @mock_patch("aiworker.llm.deepseek_adapter.subprocess.run")
    def test_file_not_found_returns_none(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = FileNotFoundError("ollama not found")
        adapter = DeepSeekAdapter()
        result = adapter.generate(
            self._make_plan(), "test", ("a.py",)
        )
        self.assertIsNone(result)

    @mock_patch("aiworker.llm.deepseek_adapter.subprocess.run")
    def test_os_error_returns_none(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = OSError("permission denied")
        adapter = DeepSeekAdapter()
        result = adapter.generate(
            self._make_plan(), "test", ("a.py",)
        )
        self.assertIsNone(result)

    @mock_patch("aiworker.llm.deepseek_adapter.subprocess.run")
    def test_seed_passed_to_prompt(self, mock_run: MagicMock) -> None:
        mock_run.return_value = self._mock_subprocess_result(
            stdout=_VALID_DIFF_OUTPUT
        )
        adapter = DeepSeekAdapter()
        adapter.generate(
            self._make_plan(), "test", ("a.py",), seed=42
        )
        call_args = mock_run.call_args
        prompt_input = call_args.kwargs.get("input", call_args[1].get("input", ""))
        self.assertIn("seed 42", prompt_input)

    @mock_patch("aiworker.llm.deepseek_adapter.subprocess.run")
    def test_correct_command(self, mock_run: MagicMock) -> None:
        mock_run.return_value = self._mock_subprocess_result(
            stdout=_VALID_DIFF_OUTPUT
        )
        adapter = DeepSeekAdapter(model_name="deepseek-coder:7b")
        adapter.generate(self._make_plan(), "test", ("a.py",))
        call_args = mock_run.call_args
        cmd = call_args[0][0] if call_args[0] else call_args.kwargs.get("args")
        self.assertEqual(cmd, ["ollama", "run", "deepseek-coder:7b"])

    @mock_patch("aiworker.llm.deepseek_adapter.subprocess.run")
    def test_env_restricted(self, mock_run: MagicMock) -> None:
        mock_run.return_value = self._mock_subprocess_result(
            stdout=_VALID_DIFF_OUTPUT
        )
        adapter = DeepSeekAdapter()
        adapter.generate(self._make_plan(), "test", ("a.py",))
        call_args = mock_run.call_args
        env = call_args.kwargs.get("env", {})
        # Should only contain allowlisted keys
        for key in env:
            self.assertIn(
                key, ("PATH", "HOME", "OLLAMA_HOST", "OLLAMA_MODELS")
            )


class TestDeepSeekAdapterProtocol(unittest.TestCase):
    """Verify PatchGenerator protocol compliance."""

    def test_satisfies_protocol(self) -> None:
        from aiworker.autonomy.controller import PatchGenerator
        adapter = DeepSeekAdapter()
        self.assertIsInstance(adapter, PatchGenerator)

    def test_generate_signature_matches(self) -> None:
        """Verify the method accepts all PatchGenerator parameters."""
        import inspect
        sig = inspect.signature(DeepSeekAdapter.generate)
        params = list(sig.parameters.keys())
        self.assertEqual(params, ["self", "plan", "goal", "allowed_files", "seed"])


if __name__ == "__main__":
    unittest.main()
