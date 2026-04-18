from __future__ import annotations

import argparse
import json
import threading
import time
from pathlib import Path
from typing import Any, Sequence
from uuid import uuid4

from agents.bug_bounty.analyzer_agent import AnalyzerAgent
from agents.bug_bounty.exploit_validator_agent import ExploitValidatorAgent
from agents.bug_bounty.recon_agent import ReconAgent
from agents.bug_bounty.reporter_agent import ReporterAgent
from agents.bug_bounty.scanner_agent import ScannerAgent
from agents.trading.data_agent import DataAgent
from agents.trading.execution_agent import ExecutionAgent
from agents.trading.portfolio_agent import PortfolioAgent
from agents.trading.risk_agent import RiskAgent
from agents.trading.strategy_agent import StrategyAgent
from aiworker.config import settings
from aiworker.executor import Executor
from aiworker.logger import get_logger
from aiworker.message_bus import Event, EventType, bus
from aiworker.storage import Storage
from aiworker.validator import Validator
from aiworker.verifier import Verifier


def _ensure_runtime() -> None:
    settings.workspace_dir.mkdir(parents=True, exist_ok=True)
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)


def _build_shared_components() -> tuple[Validator, Executor, Verifier, Storage]:
    _ensure_runtime()
    storage = Storage(settings.db_path)
    storage.init_db()
    return Validator(), Executor(), Verifier(), storage


def run_bug_bounty(target: str | None = None) -> str:
    run_id = str(uuid4())
    validator, executor, verifier, storage = _build_shared_components()
    logger = get_logger("runner")
    bus.clear()

    recon = ReconAgent(bus, validator, executor, verifier, storage)
    scanner = ScannerAgent(bus, validator, executor, verifier, storage)
    analyzer = AnalyzerAgent(bus, validator, executor, verifier, storage)
    exploit_validator = ExploitValidatorAgent(bus, validator, executor, verifier, storage)
    reporter = ReporterAgent(bus, validator, executor, verifier, storage)

    report_ready = threading.Event()
    report_payload: dict[str, Any] = {}

    def on_report_ready(event: Event) -> None:
        report_payload.update(event.payload)
        report_ready.set()

    bus.subscribe(EventType.RECON_COMPLETE, scanner.handle_recon_complete)
    bus.subscribe(EventType.SCAN_COMPLETE, analyzer.handle_scan_complete)
    bus.subscribe(EventType.ANALYSIS_COMPLETE, exploit_validator.handle_analysis_complete)
    bus.subscribe(EventType.EXPLOIT_VALIDATED, reporter.handle_exploit_validated)
    bus.subscribe(EventType.REPORT_READY, on_report_ready)

    target_url = target or settings.bug_bounty_target
    recon.execute_loop(target_url, run_id)
    completed = report_ready.wait(timeout=60.0)
    if not completed:
        raise TimeoutError("bug bounty pipeline timed out waiting for report.ready")

    logger.info("bug bounty completed run_id=%s report=%s", run_id, report_payload.get("report_path"))
    return run_id


def run_trading_lab(duration_seconds: float = 60.0) -> str:
    run_id = str(uuid4())
    validator, executor, verifier, storage = _build_shared_components()
    logger = get_logger("runner")
    bus.clear()

    data_agent = DataAgent(bus, validator, executor, verifier, storage)
    strategy_agent = StrategyAgent(bus, validator, executor, verifier, storage)
    risk_agent = RiskAgent(bus, validator, executor, verifier, storage)
    execution_agent = ExecutionAgent(bus, validator, executor, verifier, storage)
    portfolio_agent = PortfolioAgent(bus, validator, executor, verifier, storage)

    bus.subscribe(EventType.MARKET_DATA_UPDATED, strategy_agent.handle_market_data)
    bus.subscribe(EventType.SIGNAL_GENERATED, risk_agent.handle_signal_generated)
    bus.subscribe(EventType.RISK_APPROVED, execution_agent.handle_risk_approved)
    bus.subscribe(EventType.ORDER_EXECUTED, portfolio_agent.handle_order_executed)
    bus.subscribe(EventType.PORTFOLIO_UPDATED, risk_agent.handle_portfolio_updated)
    bus.subscribe(EventType.SYSTEM_SHUTDOWN, data_agent.handle_shutdown)

    polling_thread = threading.Thread(
        target=data_agent.poll_market_data,
        args=(run_id,),
        name="DataAgentPolling",
        daemon=True,
    )
    polling_thread.start()

    time.sleep(duration_seconds)
    bus.publish(
        Event(
            event_type=EventType.SYSTEM_SHUTDOWN,
            source_agent="runner",
            payload={"reason": "duration elapsed"},
            run_id=run_id,
        )
    )
    polling_thread.join(timeout=10.0)

    summary = storage.get_run_summary(run_id)
    logger.info("trading summary: %s", json.dumps(summary, default=str))
    print(json.dumps(summary, indent=2, default=str))
    return run_id


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local-first multi-agent system.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    bug_parser = subparsers.add_parser("bug-bounty", help="Run the bug bounty pipeline.")
    bug_parser.add_argument("--target", default=None, help="Override the bug bounty target URL.")

    trading_parser = subparsers.add_parser("trading", help="Run the trading lab.")
    trading_parser.add_argument("--duration", type=float, default=60.0, help="Trading duration in seconds.")

    both_parser = subparsers.add_parser("both", help="Run both subsystems.")
    both_parser.add_argument("--duration", type=float, default=30.0, help="Trading duration in seconds.")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "bug-bounty":
        run_id = run_bug_bounty(args.target)
        print(run_id)
        return 0
    if args.command == "trading":
        run_id = run_trading_lab(args.duration)
        print(run_id)
        return 0

    bug_run_id = run_bug_bounty(None)
    trading_run_id = run_trading_lab(args.duration)
    print(json.dumps({"bug_bounty_run_id": bug_run_id, "trading_run_id": trading_run_id}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
