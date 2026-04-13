"""Tests for the persistent experience memory system (Milestone 3).

Covers database initialisation, CRUD operations, foreign key
enforcement, retrieval, SQL injection safety, cross-session
persistence, and engine integration.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import textwrap
from pathlib import Path

import pytest

from aiworker.memory.database import Database
from aiworker.memory.models import (
    ApprovalResultRecord,
    ChangeAttemptRecord,
    SandboxResultRecord,
    ValidationResultRecord,
)
from aiworker.memory.repository import MemoryRepository
from aiworker.memory.retrieval import find_similar_attempts
from aiworker.self_modify.change_request import ChangeRequest
from aiworker.self_modify.engine import process_change_request


# ---------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------


@pytest.fixture()
def db() -> Database:
    """Return an initialised in-memory database."""
    database = Database(":memory:")
    database.initialise()
    return database


@pytest.fixture()
def repo(db: Database) -> MemoryRepository:
    """Return a repository backed by the in-memory database."""
    return MemoryRepository(db)


# ---------------------------------------------------------------
# 1. Database initialisation
# ---------------------------------------------------------------


class TestDatabaseInit:
    """Verify database and table creation."""

    def test_tables_created(self, db: Database) -> None:
        """All four tables must exist after initialisation."""
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        names = [r[0] for r in rows]
        assert "change_attempts" in names
        assert "validation_results" in names
        assert "sandbox_results" in names
        assert "approval_results" in names

    def test_idempotent_init(self, db: Database) -> None:
        """Calling initialise() twice must not raise."""
        db.initialise()  # second call
        with db.connect() as conn:
            count = conn.execute(
                "SELECT count(*) FROM sqlite_master WHERE type='table'"
            ).fetchone()[0]
        assert count >= 4

    def test_foreign_keys_enabled(self, db: Database) -> None:
        """PRAGMA foreign_keys must be ON for every connection."""
        with db.connect() as conn:
            fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert fk == 1


# ---------------------------------------------------------------
# 2. Foreign key constraint enforcement
# ---------------------------------------------------------------


class TestForeignKeys:
    """Verify FK constraints are enforced at the database level."""

    def test_validation_fk_enforced(self, db: Database) -> None:
        """Inserting a validation_result with a bogus attempt_id must fail."""
        with pytest.raises(sqlite3.IntegrityError):
            with db.connect() as conn:
                conn.execute(
                    "INSERT INTO validation_results "
                    "(id, attempt_id, validation_passed, reason) "
                    "VALUES (?, ?, ?, ?)",
                    ("v1", "nonexistent_attempt", True, "ok"),
                )

    def test_sandbox_fk_enforced(self, db: Database) -> None:
        """Inserting a sandbox_result with a bogus attempt_id must fail."""
        with pytest.raises(sqlite3.IntegrityError):
            with db.connect() as conn:
                conn.execute(
                    "INSERT INTO sandbox_results "
                    "(id, attempt_id, success, tests_passed, tests_failed, execution_time) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    ("s1", "nonexistent_attempt", True, 5, 0, 1.0),
                )

    def test_approval_fk_enforced(self, db: Database) -> None:
        """Inserting an approval_result with a bogus attempt_id must fail."""
        with pytest.raises(sqlite3.IntegrityError):
            with db.connect() as conn:
                conn.execute(
                    "INSERT INTO approval_results "
                    "(id, attempt_id, approved, approval_required, final_reason) "
                    "VALUES (?, ?, ?, ?, ?)",
                    ("a1", "nonexistent_attempt", False, True, "nope"),
                )


# ---------------------------------------------------------------
# 3. Insert and retrieve records
# ---------------------------------------------------------------


class TestInsertRetrieve:
    """Verify that inserts round-trip correctly."""

    def test_insert_and_get_attempt(self, repo: MemoryRepository) -> None:
        """A stored attempt must be retrievable by its ID."""
        attempt = repo.insert_change_attempt(
            goal="Add subtract function",
            risk_level="low",
            allowed_files=["math_utils.py"],
        )
        fetched = repo.get_attempt_by_id(attempt.id)
        assert fetched is not None
        assert fetched.goal == "Add subtract function"
        assert fetched.risk_level == "low"
        assert fetched.get_allowed_files_list() == ["math_utils.py"]

    def test_insert_validation_result(self, repo: MemoryRepository) -> None:
        """Validation result must be linked to the correct attempt."""
        attempt = repo.insert_change_attempt("g", "low", ["a.py"])
        vr = repo.insert_validation_result(attempt.id, True, "passed")
        fetched = repo.get_validation_for_attempt(attempt.id)
        assert fetched is not None
        assert fetched.validation_passed is True
        assert fetched.reason == "passed"
        assert fetched.attempt_id == attempt.id

    def test_insert_sandbox_result(self, repo: MemoryRepository) -> None:
        """Sandbox result must store all execution metrics."""
        attempt = repo.insert_change_attempt("g", "low", ["a.py"])
        sr = repo.insert_sandbox_result(attempt.id, True, 5, 1, 2.34)
        fetched = repo.get_sandbox_for_attempt(attempt.id)
        assert fetched is not None
        assert fetched.success is True
        assert fetched.tests_passed == 5
        assert fetched.tests_failed == 1
        assert abs(fetched.execution_time - 2.34) < 0.01

    def test_insert_approval_result(self, repo: MemoryRepository) -> None:
        """Approval result must store decision details."""
        attempt = repo.insert_change_attempt("g", "medium", ["a.py"])
        ar = repo.insert_approval_result(attempt.id, False, True, "needs review")
        fetched = repo.get_approval_for_attempt(attempt.id)
        assert fetched is not None
        assert fetched.approved is False
        assert fetched.approval_required is True
        assert fetched.final_reason == "needs review"

    def test_get_nonexistent_attempt(self, repo: MemoryRepository) -> None:
        """Querying a non-existent ID must return None."""
        assert repo.get_attempt_by_id("does-not-exist") is None

    def test_get_nonexistent_validation(self, repo: MemoryRepository) -> None:
        """Querying validation for missing attempt must return None."""
        assert repo.get_validation_for_attempt("nope") is None

    def test_get_nonexistent_sandbox(self, repo: MemoryRepository) -> None:
        """Querying sandbox result for missing attempt must return None."""
        assert repo.get_sandbox_for_attempt("nope") is None

    def test_get_nonexistent_approval(self, repo: MemoryRepository) -> None:
        """Querying approval result for missing attempt must return None."""
        assert repo.get_approval_for_attempt("nope") is None


# ---------------------------------------------------------------
# 4. Retrieval: last N, goal search, limit
# ---------------------------------------------------------------


class TestRetrieval:
    """Verify list/search retrieval functions."""

    def test_last_n_attempts(self, repo: MemoryRepository) -> None:
        """get_last_n_attempts must return newest first, limited to N."""
        for i in range(5):
            repo.insert_change_attempt(f"goal-{i}", "low", ["a.py"])
        results = repo.get_last_n_attempts(3)
        assert len(results) == 3
        # Newest first (highest index was last inserted)
        assert results[0].goal == "goal-4"

    def test_retrieval_limit_respected(self, repo: MemoryRepository) -> None:
        """Limit parameter must cap the result count."""
        for i in range(10):
            repo.insert_change_attempt(f"goal-{i}", "low", ["a.py"])
        assert len(repo.get_last_n_attempts(5)) == 5

    def test_goal_search(self, repo: MemoryRepository) -> None:
        """get_attempts_by_goal must match substring."""
        repo.insert_change_attempt("Add multiply function", "low", ["math.py"])
        repo.insert_change_attempt("Fix division bug", "medium", ["math.py"])
        repo.insert_change_attempt("Add logging", "low", ["log.py"])
        results = repo.get_attempts_by_goal("Add")
        assert len(results) == 2
        goals = {r.goal for r in results}
        assert "Add multiply function" in goals
        assert "Add logging" in goals

    def test_goal_search_no_match(self, repo: MemoryRepository) -> None:
        """Search with no matching goals must return empty list."""
        repo.insert_change_attempt("Refactor", "low", ["a.py"])
        assert repo.get_attempts_by_goal("zzzzz") == []

    def test_find_similar_attempts(self, db: Database) -> None:
        """find_similar_attempts convenience function works."""
        repo = MemoryRepository(db)
        repo.insert_change_attempt("Refactor auth module", "high", ["auth.py"])
        repo.insert_change_attempt("Add auth tests", "low", ["test_auth.py"])
        repo.insert_change_attempt("Fix UI crash", "medium", ["ui.py"])
        results = find_similar_attempts(db, "auth")
        assert len(results) == 2

    def test_find_similar_empty_goal(self, db: Database) -> None:
        """find_similar_attempts with empty goal returns empty list."""
        assert find_similar_attempts(db, "") == []
        assert find_similar_attempts(db, "   ") == []

    def test_find_similar_limit(self, db: Database) -> None:
        """find_similar_attempts respects limit parameter."""
        repo = MemoryRepository(db)
        for i in range(10):
            repo.insert_change_attempt(f"refactor-{i}", "low", ["a.py"])
        results = find_similar_attempts(db, "refactor", limit=3)
        assert len(results) == 3


# ---------------------------------------------------------------
# 5. SQL injection safety
# ---------------------------------------------------------------


class TestSQLInjection:
    """Verify that SQL injection is impossible."""

    def test_goal_search_injection(self, repo: MemoryRepository) -> None:
        """SQL injection via goal search must be harmless."""
        repo.insert_change_attempt("normal goal", "low", ["a.py"])
        # Attempt injection
        malicious = "'; DROP TABLE change_attempts; --"
        results = repo.get_attempts_by_goal(malicious)
        assert results == []
        # Table must still exist
        assert repo.get_last_n_attempts(1) != []

    def test_find_similar_injection(self, db: Database) -> None:
        """SQL injection via find_similar_attempts must be harmless."""
        repo = MemoryRepository(db)
        repo.insert_change_attempt("safe goal", "low", ["a.py"])
        results = find_similar_attempts(db, "' OR 1=1 --")
        assert results == []
        # Data still intact
        assert len(repo.get_last_n_attempts(10)) == 1

    def test_insert_injection_in_goal(self, repo: MemoryRepository) -> None:
        """SQL injection in insert fields must be stored as literal text."""
        malicious_goal = "'; DROP TABLE change_attempts; --"
        attempt = repo.insert_change_attempt(malicious_goal, "low", ["a.py"])
        fetched = repo.get_attempt_by_id(attempt.id)
        assert fetched is not None
        assert fetched.goal == malicious_goal


# ---------------------------------------------------------------
# 6. Cross-session persistence
# ---------------------------------------------------------------


class TestPersistence:
    """Verify data survives across database connections."""

    def test_data_persists_between_sessions(self, tmp_path: Path) -> None:
        """Data written in one session must be readable in another."""
        db_path = str(tmp_path / "persist_test.db")

        # Session 1: write
        db1 = Database(db_path)
        db1.initialise()
        repo1 = MemoryRepository(db1)
        attempt = repo1.insert_change_attempt("persist me", "low", ["x.py"])
        attempt_id = attempt.id

        # Session 2: read (new Database object)
        db2 = Database(db_path)
        db2.initialise()
        repo2 = MemoryRepository(db2)
        fetched = repo2.get_attempt_by_id(attempt_id)
        assert fetched is not None
        assert fetched.goal == "persist me"


# ---------------------------------------------------------------
# 7. Model dataclass behaviour
# ---------------------------------------------------------------


class TestModels:
    """Verify model dataclass contracts."""

    def test_change_attempt_frozen(self) -> None:
        """ChangeAttemptRecord must be immutable."""
        rec = ChangeAttemptRecord(
            id="1", goal="g", risk_level="low",
            allowed_files='["a.py"]', timestamp="2025-01-01T00:00:00",
        )
        with pytest.raises(AttributeError):
            rec.goal = "modified"  # type: ignore[misc]

    def test_allowed_files_list_parsing(self) -> None:
        """get_allowed_files_list must deserialise JSON correctly."""
        rec = ChangeAttemptRecord(
            id="1", goal="g", risk_level="low",
            allowed_files='["a.py", "b.py"]', timestamp="now",
        )
        assert rec.get_allowed_files_list() == ["a.py", "b.py"]

    def test_allowed_files_invalid_json(self) -> None:
        """get_allowed_files_list must handle non-list JSON gracefully."""
        rec = ChangeAttemptRecord(
            id="1", goal="g", risk_level="low",
            allowed_files='"not_a_list"', timestamp="now",
        )
        assert rec.get_allowed_files_list() == []

    def test_validation_result_frozen(self) -> None:
        """ValidationResultRecord must be immutable."""
        rec = ValidationResultRecord(
            id="1", attempt_id="a", validation_passed=True, reason="ok",
        )
        with pytest.raises(AttributeError):
            rec.reason = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------
# 8. Engine integration with memory
# ---------------------------------------------------------------


class TestEngineIntegration:
    """Verify engine persists results to memory when database is provided."""

    @staticmethod
    def _make_workspace() -> str:
        """Create a minimal workspace with a Python file and test."""
        d = tempfile.mkdtemp(prefix="mem_ws_")
        ws = os.path.join(d, "workspace")
        os.makedirs(ws)
        with open(os.path.join(ws, "math_utils.py"), "w") as f:
            f.write("def add(a, b):\n    return a + b\n")
        with open(os.path.join(ws, "test_math_utils.py"), "w") as f:
            f.write(textwrap.dedent("""\
                from math_utils import add
                def test_add():
                    assert add(1, 2) == 3
            """))
        return ws

    VALID_PATCH = textwrap.dedent("""\
        --- a/math_utils.py
        +++ b/math_utils.py
        @@ -1,2 +1,6 @@
         def add(a, b):
             return a + b
        +
        +
        +def multiply(a, b):
        +    return a * b
    """)

    def test_engine_persists_successful_attempt(self) -> None:
        """Engine must save all records when database is provided."""
        ws = self._make_workspace()
        db = Database(":memory:")
        db.initialise()
        repo = MemoryRepository(db)

        cr = ChangeRequest(
            goal="Add multiply",
            allowed_files=["math_utils.py", "test_math_utils.py"],
            max_lines_changed=50,
            tests_required=False,
            risk_level="low",
        )

        try:
            result = process_change_request(
                cr, self.VALID_PATCH, ws, timeout=60, database=db,
            )
            # Verify records were persisted
            attempts = repo.get_last_n_attempts(10)
            assert len(attempts) == 1
            attempt = attempts[0]
            assert attempt.goal == "Add multiply"

            vr = repo.get_validation_for_attempt(attempt.id)
            assert vr is not None
            assert vr.validation_passed is True

            sr = repo.get_sandbox_for_attempt(attempt.id)
            assert sr is not None
            assert sr.success is True

            ar = repo.get_approval_for_attempt(attempt.id)
            assert ar is not None
            assert ar.approval_required is True
        finally:
            shutil.rmtree(os.path.dirname(ws), ignore_errors=True)

    def test_engine_persists_validation_failure(self) -> None:
        """Even failed validations must be persisted."""
        ws = self._make_workspace()
        db = Database(":memory:")
        db.initialise()
        repo = MemoryRepository(db)

        cr = ChangeRequest(
            goal="Bad patch",
            allowed_files=["math_utils.py"],
            max_lines_changed=5,
            risk_level="low",
        )
        bad_patch = "--- a/../../etc/passwd\n+++ b/../../etc/passwd\n@@ -0,0 +1 @@\n+hacked\n"

        try:
            result = process_change_request(
                cr, bad_patch, ws, timeout=60, database=db,
            )
            assert not result.validation_passed

            attempts = repo.get_last_n_attempts(10)
            assert len(attempts) == 1

            vr = repo.get_validation_for_attempt(attempts[0].id)
            assert vr is not None
            assert vr.validation_passed is False

            # No sandbox result for failed validation
            sr = repo.get_sandbox_for_attempt(attempts[0].id)
            assert sr is None

            # Approval result still stored
            ar = repo.get_approval_for_attempt(attempts[0].id)
            assert ar is not None
            assert ar.approved is False
        finally:
            shutil.rmtree(os.path.dirname(ws), ignore_errors=True)

    def test_engine_without_database_still_works(self) -> None:
        """Engine must function normally when no database is provided."""
        ws = self._make_workspace()
        cr = ChangeRequest(
            goal="No DB",
            allowed_files=["math_utils.py"],
            max_lines_changed=50,
            risk_level="low",
        )
        try:
            result = process_change_request(
                cr, self.VALID_PATCH, ws, timeout=60,
            )
            assert result.validation_passed
        finally:
            shutil.rmtree(os.path.dirname(ws), ignore_errors=True)

    def test_workspace_not_modified_with_memory(self) -> None:
        """Workspace must remain unchanged even with memory enabled."""
        ws = self._make_workspace()
        db = Database(":memory:")
        db.initialise()
        original = open(os.path.join(ws, "math_utils.py")).read()

        cr = ChangeRequest(
            goal="Memory test",
            allowed_files=["math_utils.py"],
            max_lines_changed=50,
            risk_level="low",
        )
        try:
            process_change_request(
                cr, self.VALID_PATCH, ws, timeout=60, database=db,
            )
            after = open(os.path.join(ws, "math_utils.py")).read()
            assert original == after
        finally:
            shutil.rmtree(os.path.dirname(ws), ignore_errors=True)
