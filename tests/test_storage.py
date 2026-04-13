from __future__ import annotations

from datetime import datetime, timezone
from storage import StepRecord, Storage


def _record(run_id: str, step_number: int, status: str, duration: float) -> StepRecord:
    return StepRecord(
        run_id=run_id,
        step_number=step_number,
        tool_name="list_files",
        parameters={"path": "."},
        reason="List files",
        verification_status=status,
        output_summary="output",
        error=None,
        duration_seconds=duration,
        timestamp=datetime.now(timezone.utc),
    )


def test_init_db_creates_tables_without_error(db_path) -> None:
    storage = Storage(db_path)

    storage.init_db()

    assert storage.db_path.exists()


def test_save_step_persists_step_record_correctly(db_path) -> None:
    storage = Storage(db_path)
    storage.init_db()
    record = _record("run-1", 1, "SUCCESS", 0.5)

    storage.save_step(record)

    stored = storage.get_run("run-1")
    assert len(stored) == 1
    assert stored[0].run_id == "run-1"


def test_get_run_returns_correct_records_for_run_id(db_path) -> None:
    storage = Storage(db_path)
    storage.init_db()
    storage.save_step(_record("run-1", 1, "SUCCESS", 0.5))
    storage.save_step(_record("run-1", 2, "FAILURE", 0.2))
    storage.save_step(_record("run-2", 1, "SUCCESS", 0.1))

    records = storage.get_run("run-1")

    assert [record.step_number for record in records] == [1, 2]


def test_get_run_returns_empty_list_for_unknown_run_id(db_path) -> None:
    storage = Storage(db_path)
    storage.init_db()

    assert storage.get_run("missing") == []


def test_get_all_runs_returns_list_of_run_ids(db_path) -> None:
    storage = Storage(db_path)
    storage.init_db()
    storage.save_step(_record("run-a", 1, "SUCCESS", 0.2))
    storage.save_step(_record("run-b", 1, "FAILURE", 0.4))

    assert storage.get_all_runs() == ["run-a", "run-b"]


def test_get_summary_returns_correct_counts_and_duration(db_path) -> None:
    storage = Storage(db_path)
    storage.init_db()
    storage.save_step(_record("run-1", 1, "SUCCESS", 0.3))
    storage.save_step(_record("run-1", 2, "FAILURE", 0.7))
    storage.save_step(_record("run-1", 3, "UNVERIFIED", 0.2))

    summary = storage.get_summary("run-1")

    assert summary == {
        "total_steps": 3,
        "success_count": 1,
        "failure_count": 1,
        "unverified_count": 1,
        "total_duration": 1.2,
    }
