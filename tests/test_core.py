from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tools
from critic.evaluator import evaluate
from executor import validate_arguments
from executor import Executor
from friday.planner import (
    Planner,
    SAFE_FALLBACK,
    TOOL_SCHEMA,
    _default_args,
    _fallback_plan,
    _sanitize,
    calibrate_threshold,
    strip_json_fences,
)
import runner
from interpreter.engine import interpret
from memory.skills import SkillLibrary
from tools import (
    create_directory,
    delete_file,
    diff_files,
    execute_python,
    execute_python_file,
    lint_file,
    patch_file,
    run_command,
    summarize_file,
    web_fetch,
    write_code,
)


class TestInterpreter(unittest.TestCase):
    def test_none_is_empty(self) -> None:
        self.assertEqual(interpret(None)["type"], "empty")

    def test_empty_string_is_empty(self) -> None:
        self.assertEqual(interpret("")["type"], "empty")

    def test_empty_list_is_empty(self) -> None:
        self.assertEqual(interpret([])["type"], "empty")

    def test_text_summary_contains_content(self) -> None:
        result = interpret("hello world")
        self.assertEqual(result["type"], "text")
        self.assertIn("hello", result["summary"])

    def test_long_text_is_truncated(self) -> None:
        self.assertLessEqual(len(interpret("x" * 1000)["summary"]), 303)

    def test_list_key_info_preserved(self) -> None:
        result = interpret(["a", "b", "c"])
        self.assertEqual(result["type"], "list")
        self.assertEqual(result["key_info"], ["a", "b", "c"])


class TestCritic(unittest.TestCase):
    def test_error_marks_result_incorrect(self) -> None:
        verdict = evaluate("t", "read_file", {}, {"type": "text", "summary": "x", "key_info": []}, "RuntimeError")
        self.assertEqual(verdict["decision"], "incorrect")
        self.assertEqual(verdict["score"], 0.0)

    def test_empty_output_marks_result_incorrect(self) -> None:
        verdict = evaluate("t", "list_files", {}, {"type": "empty", "summary": "", "key_info": []}, None)
        self.assertEqual(verdict["decision"], "incorrect")

    def test_non_empty_known_tool_marks_result_correct(self) -> None:
        verdict = evaluate("t", "list_files", {}, {"type": "list", "summary": "3 items", "key_info": []}, None)
        self.assertEqual(verdict["decision"], "correct")
        self.assertGreaterEqual(verdict["score"], 0.7)

    def test_unknown_tool_with_non_empty_output_is_correct(self) -> None:
        verdict = evaluate("t", "new_tool", {}, {"type": "dict", "summary": "x", "key_info": ["a"]}, None)
        self.assertEqual(verdict["decision"], "correct")
        self.assertGreaterEqual(verdict["score"], 0.85)


class TestValidateArguments(unittest.TestCase):
    def test_read_file_requires_path(self) -> None:
        valid, reason = validate_arguments("read_file", {})
        self.assertFalse(valid)
        self.assertTrue(reason)

    def test_read_file_rejects_empty_path(self) -> None:
        valid, reason = validate_arguments("read_file", {"path": ""})
        self.assertFalse(valid)
        self.assertTrue(reason)

    def test_web_search_rejects_blank_query(self) -> None:
        valid, reason = validate_arguments("web_search", {"query": "  "})
        self.assertFalse(valid)
        self.assertTrue(reason)

    def test_system_info_accepts_empty_arguments(self) -> None:
        self.assertEqual(validate_arguments("system_info", {}), (True, ""))

    def test_web_fetch_requires_http_scheme(self) -> None:
        valid, reason = validate_arguments("web_fetch", {"url": "example.com"})
        self.assertFalse(valid)
        self.assertIn("http", reason)

    def test_write_file_rejects_system_path(self) -> None:
        valid, reason = validate_arguments("write_file", {"path": "/etc/passwd", "content": "x"})
        self.assertFalse(valid)
        self.assertIn("system path", reason)

    def test_list_files_defaults_path(self) -> None:
        arguments: dict[str, str] = {}
        valid, reason = validate_arguments("list_files", arguments)
        self.assertTrue(valid)
        self.assertEqual(reason, "")
        self.assertEqual(arguments["path"], ".")


class TestHeuristicFallback(unittest.TestCase):
    def test_default_args_extracts_read_file_path(self) -> None:
        self.assertEqual(_default_args("read_file", "read file config.py"), {"path": "config.py"})

    def test_default_args_extracts_execute_python_code(self) -> None:
        self.assertEqual(_default_args("execute_python", "execute python code: print(2 + 2)"), {"code": "print(2 + 2)"})

    def test_default_args_execute_python_file_requires_python_path(self) -> None:
        self.assertEqual(_default_args("execute_python_file", "run python file 2)"), {"path": ""})

    def test_default_args_extracts_directory_target(self) -> None:
        self.assertEqual(_default_args("list_files", "list files in agents directory"), {"path": "agents"})

    def test_heuristic_fallback_selects_read_file(self) -> None:
        with patch("friday.planner.OllamaBackend"), patch("friday.planner.ModelRouter"):
            planner = Planner()
        result = planner._heuristic_fallback("read file config.py")
        self.assertEqual(result["tool"], "read_file")
        self.assertEqual(result["arguments"]["path"], "config.py")

    def test_fallback_plan_decomposes_then_sequence(self) -> None:
        self.assertEqual(
            _fallback_plan("list all python files then read executor.py"),
            [
                {"step": 1, "task": "list all python files"},
                {"step": 2, "task": "read executor.py"},
            ],
        )

    def test_fallback_plan_resolves_entry_point_summary(self) -> None:
        with patch.object(Path, "exists", autospec=True, side_effect=lambda path: path.name == "runner.py"):
            plan = _fallback_plan("read the main entry point, and summarize what it does")
        self.assertEqual(plan[0]["task"], "read runner.py")
        self.assertEqual(plan[1]["task"], "summarize runner.py")

    def test_parse_plan_uses_fallback_when_llm_collapses_multi_step_task(self) -> None:
        with patch("friday.planner.OllamaBackend"), patch("friday.planner.ModelRouter"):
            planner = Planner()
        parsed = planner._parse_plan('[{"step":1,"task":"list all python files"}]', "list all python files then read executor.py")
        self.assertEqual(
            parsed,
            [
                {"step": 1, "task": "list all python files"},
                {"step": 2, "task": "read executor.py"},
            ],
        )

    def test_heuristic_fallback_uses_safe_default_for_unknown_text(self) -> None:
        with patch("friday.planner.OllamaBackend"), patch("friday.planner.ModelRouter"):
            planner = Planner()
        result = planner._heuristic_fallback("xyzzy frobnicate")
        self.assertEqual(result["tool"], SAFE_FALLBACK["tool"])
        self.assertEqual(result["arguments"], SAFE_FALLBACK["arguments"])

    def test_strip_json_fences_removes_markdown_wrapping(self) -> None:
        self.assertEqual(strip_json_fences("```json\n{\"tool\":\"read_file\"}\n```"), "{\"tool\":\"read_file\"}")

    def test_sanitize_removes_control_characters(self) -> None:
        sanitized = _sanitize("task\x00with\nnewline")
        self.assertNotIn("\x00", sanitized)
        self.assertNotIn("\n", sanitized)


class TestFuzz(unittest.TestCase):
    MALFORMED_LLM_OUTPUTS = [
        "",
        "   ",
        "I will use the read_file tool to read your file.",
        "```json\n{broken\n```",
        '{"tool": "evil_tool", "arguments": {}, "confidence": 0.9}',
        '{"tool": "read_file"}',
        '{"arguments": {"path": "x"}}',
        '{"tool": "read_file", "arguments": {"path": "x"}, "confidence": "high"}',
        "null",
        "[]",
        "[1, 2, 3]",
        "true",
        "SELECT * FROM tools;",
        "\x00\x01\x02",
        "A" * 10000,
        '{"tool": null, "arguments": null, "confidence": null}',
    ]

    def test_select_tool_never_crashes(self) -> None:
        with patch("friday.planner.OllamaBackend"), patch("friday.planner.ModelRouter"):
            planner = Planner()
        for raw in self.MALFORMED_LLM_OUTPUTS:
            planner._llm = lambda prompt, system="", raw=raw: raw
            try:
                result = planner.select_tool("read file config.py", {})
                self.assertIn(result["tool"], list(TOOL_SCHEMA.keys()) + ["none"])
                self.assertIsInstance(result["arguments"], dict)
                self.assertIsInstance(result["confidence"], float)
            except Exception as exc:
                self.fail(f"select_tool raised {exc} for input: {repr(raw)}")

    def test_interpret_never_crashes(self) -> None:
        inputs = [None, "", [], {}, 0, False, b"bytes", object(), "x" * 10000, [None] * 100, {"key": None}, float("inf"), float("nan")]
        for value in inputs:
            try:
                result = interpret(value)
                self.assertIn(result["type"], ["text", "list", "dict", "empty", "error"])
            except Exception as exc:
                self.fail(f"interpret raised {exc} for input: {repr(value)}")


class TestPhaseOneHardening(unittest.TestCase):
    def test_run_command_blocks_python_inline_execution(self) -> None:
        result = run_command("python3 -c 'import os; os.system(\"id\")'")
        self.assertFalse(result["success"])

    def test_run_command_blocks_absolute_shell_binary(self) -> None:
        result = run_command("/bin/bash -lc 'echo hi'")
        self.assertFalse(result["success"])
        self.assertEqual(result.get("error"), "blocked binary")

    def test_run_command_rejects_empty_command(self) -> None:
        result = run_command("")
        self.assertFalse(result["success"])

    def test_web_fetch_blocks_private_ip(self) -> None:
        result = web_fetch("http://169.254.169.254/")
        self.assertEqual(result["error"], "private IP blocked")

    def test_web_fetch_does_not_follow_redirects(self) -> None:
        class Response:
            status_code = 302
            text = ""

        with patch("tools.requests.get", return_value=Response()):
            result = web_fetch("https://example.com")
        self.assertEqual(result["error"], "redirect not followed")

    def test_strip_json_fences_handles_json_prefix(self) -> None:
        self.assertEqual(strip_json_fences('json\n{"tool":"read_file"}\n'), '{"tool":"read_file"}')

    def test_sanitize_limits_length(self) -> None:
        sanitized = _sanitize("a" * 1000)
        self.assertLessEqual(len(sanitized), 500)


class TestNewTools(unittest.TestCase):
    def test_write_code_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = str(Path(tmpdir) / "hello.py")
            with patch("tools._llm_text", return_value="print('hello')\n"):
                result = write_code(target, "python", "write hello world")
            self.assertTrue(result["success"])
            self.assertTrue(Path(target).exists())

    def test_write_code_returns_error_on_llm_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = str(Path(tmpdir) / "hello.py")
            with patch("tools._llm_text", side_effect=RuntimeError("llm down")):
                result = write_code(target, "python", "write hello world")
            self.assertFalse(result["success"])

    def test_execute_python_success(self) -> None:
        result = execute_python("print('ok')")
        self.assertTrue(result["success"])
        self.assertIn("ok", result["stdout"])

    def test_execute_python_blocks_unsafe_code(self) -> None:
        result = execute_python("import os\nprint('nope')")
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "blocked pattern in code")

    def test_execute_python_file_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "run.py"
            path.write_text("print('file ok')\n", encoding="utf-8")
            result = execute_python_file(str(path))
        self.assertTrue(result["success"])
        self.assertIn("file ok", result["stdout"])

    def test_execute_python_file_rejects_non_python_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "run.txt"
            path.write_text("print('file ok')\n", encoding="utf-8")
            result = execute_python_file(str(path))
        self.assertFalse(result["success"])

    def test_lint_file_parses_ruff_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "lint_me.py"
            path.write_text("x=1\n", encoding="utf-8")

            class Result:
                returncode = 1
                stdout = json.dumps([{"location": {"row": 3, "column": 5}, "message": "bad"}])
                stderr = ""

            with patch("tools.subprocess.run", return_value=Result()):
                result = lint_file(str(path))
        self.assertEqual(result["linter"], "ruff")
        self.assertEqual(result["issues"][0]["line"], 3)

    def test_lint_file_handles_missing_path(self) -> None:
        result = lint_file("/tmp/does-not-exist-12345.py")
        self.assertFalse(result["success"])

    def test_web_search_falls_back_to_html_results(self) -> None:
        class ApiResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, object]:
                return {"AbstractURL": "", "RelatedTopics": []}

        class HtmlResponse:
            text = '<a class="result__a" href="https://docs.python.org/3/library/asyncio.html">asyncio docs</a>'

            def raise_for_status(self) -> None:
                return None

        with patch("tools.requests.get", side_effect=[ApiResponse(), HtmlResponse()]):
            result = tools.web_search("python asyncio documentation")
        self.assertTrue(result)
        self.assertIn("asyncio", result[0]["url"])

    def test_patch_file_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "patch.txt"
            path.write_text("alpha\nbeta\n", encoding="utf-8")
            result = patch_file(str(path), "beta", "gamma")
            updated = path.read_text(encoding="utf-8")
        self.assertTrue(result["success"])
        self.assertIn("gamma", updated)

    def test_patch_file_rejects_ambiguous_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "patch.txt"
            path.write_text("beta\nbeta\n", encoding="utf-8")
            result = patch_file(str(path), "beta", "gamma")
        self.assertFalse(result["success"])
        self.assertIn("ambiguous", result["error"])

    def test_summarize_file_parses_json_response(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "summary.py"
            path.write_text("def hello():\n    return 'hi'\n", encoding="utf-8")
            with patch(
                "tools._llm_text",
                return_value='{"summary":"short","purpose":"demo","key_functions":["hello"],"dependencies":[]}',
            ):
                result = summarize_file(str(path))
        self.assertTrue(result["success"])
        self.assertEqual(result["purpose"], "demo")

    def test_summarize_file_falls_back_on_bad_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "summary.py"
            path.write_text("print('hi')\n", encoding="utf-8")
            with patch("tools._llm_text", return_value="not json"):
                result = summarize_file(str(path))
        self.assertTrue(result["success"])
        self.assertEqual(result["purpose"], "unknown")

    def test_summarize_file_falls_back_on_llm_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "summary.py"
            path.write_text("print('hi')\n", encoding="utf-8")
            with patch("tools._llm_text", side_effect=RuntimeError("llm down")):
                result = summarize_file(str(path))
        self.assertTrue(result["success"])
        self.assertEqual(result["purpose"], "unknown")

    def test_diff_files_detects_difference(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path_a = Path(tmpdir) / "a.txt"
            path_b = Path(tmpdir) / "b.txt"
            path_a.write_text("one\n", encoding="utf-8")
            path_b.write_text("two\n", encoding="utf-8")
            result = diff_files(str(path_a), str(path_b))
        self.assertFalse(result["identical"])
        self.assertGreater(result["diff_lines"], 0)

    def test_diff_files_detects_identical_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path_a = Path(tmpdir) / "a.txt"
            path_b = Path(tmpdir) / "b.txt"
            path_a.write_text("same\n", encoding="utf-8")
            path_b.write_text("same\n", encoding="utf-8")
            result = diff_files(str(path_a), str(path_b))
        self.assertTrue(result["identical"])

    def test_create_directory_creates_missing_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "newdir"
            result = create_directory(str(path))
        self.assertTrue(result["success"])
        self.assertTrue(result["created"])

    def test_create_directory_rejects_system_path(self) -> None:
        result = create_directory("/etc/test-phase2")
        self.assertFalse(result["success"])

    def test_delete_file_moves_file_to_trash(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "trashme.txt"
            path.write_text("bye\n", encoding="utf-8")
            result = delete_file(str(path))
        self.assertTrue(result["success"])
        self.assertIn(".trash", result["moved_to"])

    def test_delete_file_rejects_missing_file(self) -> None:
        result = delete_file("/tmp/does-not-exist-12345.txt")
        self.assertFalse(result["success"])


class TestSkillLibrary(unittest.TestCase):
    def test_save_and_find_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skills_path = Path(tmpdir) / "skills.json"
            with patch("memory.skills.SKILLS_PATH", skills_path):
                library = SkillLibrary()
                library.save_skill(
                    "list python files",
                    [{"tool": "list_files", "arguments": {"path": "."}, "score": 0.9}],
                    0.9,
                )
                result = library.find_skill("list all python files in directory")
        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "list python files")

    def test_find_skill_does_not_match_broadly_related_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skills_path = Path(tmpdir) / "skills.json"
            with patch("memory.skills.SKILLS_PATH", skills_path):
                library = SkillLibrary()
                library.save_skill(
                    "list all files in the current directory",
                    [{"tool": "list_files", "arguments": {"path": "."}, "score": 0.9}],
                    0.9,
                )
                result = library.find_skill("list files in agents directory")
        self.assertIsNone(result)

    def test_save_skill_preserves_use_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skills_path = Path(tmpdir) / "skills.json"
            with patch("memory.skills.SKILLS_PATH", skills_path):
                library = SkillLibrary()
                library.save_skill(
                    "list all files in the current directory",
                    [{"tool": "list_files", "arguments": {"path": "."}, "score": 0.85}],
                    0.85,
                )
                library.increment_use("list all files in the current directory")
                library.save_skill(
                    "list all files in the current directory",
                    [{"tool": "list_files", "arguments": {"path": "."}, "score": 0.9}],
                    0.9,
                )
                skill = library.find_skill("list all files in the current directory")
        self.assertIsNotNone(skill)
        self.assertEqual(skill["use_count"], 1)

    def test_promote_from_goals_creates_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skills_path = Path(tmpdir) / "skills.json"
            goals_path = Path(tmpdir) / "goals.json"
            memory_path = Path(tmpdir) / "agent_memory.json"
            goals_path.write_text(
                json.dumps(
                    [
                        {
                            "goal": "list python files then summarize runner.py",
                            "sub_goals": ["list python files", "summarize runner.py"],
                            "results": [{"achieved": True}, {"achieved": True}],
                        }
                    ]
                ),
                encoding="utf-8",
            )
            memory_path.write_text(
                json.dumps(
                    [
                        {"task": "list python files", "tool": "list_files", "success": True, "score": 0.9},
                        {"task": "summarize runner.py", "tool": "summarize_file", "success": True, "score": 0.85},
                    ]
                ),
                encoding="utf-8",
            )
            with (
                patch("memory.skills.SKILLS_PATH", skills_path),
                patch("memory.skills.GOALS_PATH", goals_path),
                patch("memory.skills.MEMORY_PATH", memory_path),
            ):
                library = SkillLibrary()
                promoted = library.promote_from_goals()
                saved = library.find_skill("list python files then summarize runner.py")
        self.assertEqual(promoted, 1)
        self.assertIsNotNone(saved)


class TestConfidenceCalibration(unittest.TestCase):
    def test_calibrate_threshold_lowers_for_strong_recent_scores(self) -> None:
        records = [{"score": 0.9} for _ in range(10)]
        with patch("friday.planner._load_records", return_value=records):
            self.assertEqual(calibrate_threshold(), 0.5)

    def test_calibrate_threshold_raises_for_weak_recent_scores(self) -> None:
        records = [{"score": 0.4} for _ in range(10)]
        with patch("friday.planner._load_records", return_value=records):
            self.assertEqual(calibrate_threshold(), 0.75)


class TestExecutorBehavior(unittest.TestCase):
    def test_blank_task_returns_no_op_result(self) -> None:
        result = Executor().run("")
        self.assertFalse(result["goal_achieved"])
        self.assertEqual(result["steps_completed"], 0)

    def test_step_matches_task_rejects_wrong_tool(self) -> None:
        self.assertFalse(
            Executor._step_matches_task(
                "execute python code: print(2 + 2)",
                "list_files",
                {"path": "."},
                {"type": "list", "summary": "items", "key_info": []},
            )
        )

    def test_tool_reported_failure_is_treated_as_error(self) -> None:
        self.assertEqual(
            Executor._tool_reported_error("execute_python_file", {"success": False, "error": "bad path"}),
            "bad path",
        )


class TestRunner(unittest.TestCase):
    def test_empty_task_reaches_executor(self) -> None:
        with patch("runner.Executor.run", return_value={"goal_achieved": True, "run_id": "r", "task": "", "steps_completed": 1, "failures": [], "final_summary": {}, "goal_evidence": ""}):
            exit_code = runner.main([""])
        self.assertEqual(exit_code, 0)

    def test_missing_task_does_not_exit_with_argparse_error(self) -> None:
        with patch("runner.Executor.run", return_value={"goal_achieved": False, "run_id": "r", "task": "", "steps_completed": 0, "failures": [], "final_summary": {}, "goal_evidence": ""}):
            exit_code = runner.main([])
        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
