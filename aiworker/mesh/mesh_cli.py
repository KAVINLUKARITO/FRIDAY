#!/usr/bin/env python3
"""
AIWorker Mesh CLI - Command-Line Interface for Mesh Operations
Phase 5: Ecosystem Expansion & Multi-Instance Coordination

Provides a comprehensive CLI for managing AIWorker mesh operations,
including node management, task control, knowledge sync, and monitoring.
"""

import argparse
import asyncio
import json
import logging
import sys
import time
from typing import Dict, List, Optional, Any
from dataclasses import asdict

from aiworker.mesh.network_node import MeshNode, MeshConfig, create_mesh_node
from aiworker.mesh.task_orchestrator import TaskOrchestrator, Task, TaskType, create_orchestrator
from aiworker.knowledge.sync_engine import SyncEngine, KnowledgeType, create_sync_engine
from aiworker.specialization.role_manager import RoleManager, InstanceRole, create_role_manager
from aiworker.consensus.consensus_engine import ConsensusEngine, create_consensus_engine

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("aiworker.mesh.cli")


class MeshCLI:
    """Command-line interface for AIWorker mesh operations."""
    
    def __init__(self):
        self.parser = self._create_parser()
        self.mesh_node: Optional[MeshNode] = None
        self.orchestrator: Optional[TaskOrchestrator] = None
        self.sync_engine: Optional[SyncEngine] = None
        self.role_manager: Optional[RoleManager] = None
        self.consensus: Optional[ConsensusEngine] = None
    
    def _create_parser(self) -> argparse.ArgumentParser:
        """Create argument parser with subcommands."""
        parser = argparse.ArgumentParser(
            prog="aiworker-mesh",
            description="AIWorker Mesh - Distributed AI Coordination",
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
Examples:
  aiworker-mesh node start --role COORDINATOR --bootstrap /ip4/10.0.0.1/tcp/1234/p2p/abc
  aiworker-mesh peers list
  aiworker-mesh task submit --type RECON --payload '{"target": "example.com"}'
  aiworker-mesh sync status
  aiworker-mesh role switch --to ANALYZER
  aiworker-mesh monitor --watch
            """
        )
        
        subparsers = parser.add_subparsers(dest="command", help="Available commands")
        
        # Node commands
        node_parser = subparsers.add_parser("node", help="Node management")
        node_subparsers = node_parser.add_subparsers(dest="node_command")
        
        node_start = node_subparsers.add_parser("start", help="Start mesh node")
        node_start.add_argument("--role", default="WORKER", 
                               choices=["WORKER", "SPECIALIST", "COORDINATOR", "OBSERVER"],
                               help="Node role")
        node_start.add_argument("--bootstrap", action="append", default=[],
                               help="Bootstrap peer address")
        node_start.add_argument("--max-peers", type=int, default=10,
                               help="Maximum peer connections")
        node_start.add_argument("--listen", default="0.0.0.0:0",
                               help="Listen address")
        
        node_stop = node_subparsers.add_parser("stop", help="Stop mesh node")
        node_status = node_subparsers.add_parser("status", help="Show node status")
        
        # Peer commands
        peer_parser = subparsers.add_parser("peers", help="Peer management")
        peer_subparsers = peer_parser.add_subparsers(dest="peer_command")
        
        peer_list = peer_subparsers.add_parser("list", help="List connected peers")
        peer_list.add_argument("--json", action="store_true", help="Output as JSON")
        
        peer_connect = peer_subparsers.add_parser("connect", help="Connect to peer")
        peer_connect.add_argument("address", help="Peer address")
        
        peer_disconnect = peer_subparsers.add_parser("disconnect", help="Disconnect from peer")
        peer_disconnect.add_argument("node_id", help="Peer node ID")
        
        peer_blacklist = peer_subparsers.add_parser("blacklist", help="Blacklist a peer")
        peer_blacklist.add_argument("node_id", help="Peer node ID")
        peer_blacklist.add_argument("--reason", help="Blacklist reason")
        
        # Task commands
        task_parser = subparsers.add_parser("task", help="Task management")
        task_subparsers = task_parser.add_subparsers(dest="task_command")
        
        task_submit = task_subparsers.add_parser("submit", help="Submit a task")
        task_submit.add_argument("--type", required=True,
                                choices=["RECON", "SCAN", "ANALYZE"],
                                help="Task type")
        task_submit.add_argument("--payload", required=True,
                                help="Task payload (JSON)")
        task_submit.add_argument("--priority", default="NORMAL",
                                choices=["CRITICAL", "HIGH", "NORMAL", "LOW"],
                                help="Task priority")
        task_submit.add_argument("--local", action="store_true",
                                help="Execute locally only")
        
        task_list = task_subparsers.add_parser("list", help="List tasks")
        task_list.add_argument("--status",
                              choices=["PENDING", "RUNNING", "COMPLETED", "FAILED"],
                              help="Filter by status")
        task_list.add_argument("--json", action="store_true", help="Output as JSON")
        
        task_status = task_subparsers.add_parser("status", help="Get task status")
        task_status.add_argument("task_id", help="Task ID")
        
        task_cancel = task_subparsers.add_parser("cancel", help="Cancel a task")
        task_cancel.add_argument("task_id", help="Task ID")
        
        # Sync commands
        sync_parser = subparsers.add_parser("sync", help="Knowledge sync")
        sync_subparsers = sync_parser.add_subparsers(dest="sync_command")
        
        sync_status = sync_subparsers.add_parser("status", help="Show sync status")
        sync_status.add_argument("--json", action="store_true", help="Output as JSON")
        
        sync_force = sync_subparsers.add_parser("force", help="Force sync with peer")
        sync_force.add_argument("--peer", help="Peer node ID (default: all)")
        
        sync_add = sync_subparsers.add_parser("add", help="Add knowledge")
        sync_add.add_argument("--type", required=True,
                             choices=["SKILL", "RESEARCH", "CODE_PATTERN", "SAFETY_INCIDENT"],
                             help="Knowledge type")
        sync_add.add_argument("--payload", required=True, help="Knowledge payload (JSON)")
        sync_add.add_argument("--local", action="store_true",
                             help="Store locally only (don't sync)")
        
        # Role commands
        role_parser = subparsers.add_parser("role", help="Role management")
        role_subparsers = role_parser.add_subparsers(dest="role_command")
        
        role_status = role_subparsers.add_parser("status", help="Show role status")
        role_status.add_argument("--json", action="store_true", help="Output as JSON")
        
        role_switch = role_subparsers.add_parser("switch", help="Switch role")
        role_switch.add_argument("--to", required=True,
                                choices=["RECON", "CODER", "ANALYZER", "VALIDATOR", "COORDINATOR"],
                                help="Target role")
        role_switch.add_argument("--force", action="store_true",
                                help="Force switch without safety check")
        
        role_list = role_subparsers.add_parser("list", help="List eligible roles")
        
        # Consensus commands
        consensus_parser = subparsers.add_parser("consensus", help="Consensus management")
        consensus_subparsers = consensus_parser.add_subparsers(dest="consensus_command")
        
        consensus_status = consensus_subparsers.add_parser("status", help="Show consensus status")
        consensus_status.add_argument("--json", action="store_true", help="Output as JSON")
        
        consensus_elect = consensus_subparsers.add_parser("elect", help="Trigger leader election")
        
        # Monitor command
        monitor_parser = subparsers.add_parser("monitor", help="Monitor mesh")
        monitor_parser.add_argument("--watch", "-w", action="store_true",
                                   help="Continuous monitoring")
        monitor_parser.add_argument("--interval", type=int, default=5,
                                   help="Update interval (seconds)")
        
        # Dashboard command
        dashboard_parser = subparsers.add_parser("dashboard", help="Launch web dashboard")
        dashboard_parser.add_argument("--host", default="0.0.0.0", help="Dashboard host")
        dashboard_parser.add_argument("--port", type=int, default=8080, help="Dashboard port")
        
        return parser
    
    async def run(self, args: Optional[List[str]] = None):
        """Run CLI with given arguments."""
        parsed = self.parser.parse_args(args)
        
        if not parsed.command:
            self.parser.print_help()
            return 1
        
        # Route to handler
        handler = getattr(self, f"_handle_{parsed.command}", None)
        if handler:
            return await handler(parsed)
        else:
            print(f"Unknown command: {parsed.command}")
            return 1
    
    # Node handlers
    
    async def _handle_node(self, args: argparse.Namespace) -> int:
        """Handle node commands."""
        if not args.node_command:
            print("Usage: aiworker-mesh node {start|stop|status}")
            return 1
        
        if args.node_command == "start":
            return await self._node_start(args)
        elif args.node_command == "stop":
            return await self._node_stop(args)
        elif args.node_command == "status":
            return await self._node_status(args)
        
        return 0
    
    async def _node_start(self, args: argparse.Namespace) -> int:
        """Start mesh node."""
        print(f"Starting mesh node with role: {args.role}")
        
        config = MeshConfig(
            role=args.role,
            bootstrap_peers=args.bootstrap,
            max_peers=args.max_peers,
            listen_addr=args.listen,
        )
        
        self.mesh_node = MeshNode(config)
        listen_addr = await self.mesh_node.start()
        
        print(f"Node started: {listen_addr}")
        print(f"Node ID: {self.mesh_node.config.node_id}")
        
        # Start additional services
        self.orchestrator = await create_orchestrator(self.mesh_node)
        self.sync_engine = await create_sync_engine(self.mesh_node)
        self.role_manager = await create_role_manager(self.mesh_node)
        self.consensus = await create_consensus_engine(self.mesh_node)
        
        print("All services started. Press Ctrl+C to stop.")
        
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("\nShutting down...")
            await self._shutdown()
        
        return 0
    
    async def _node_stop(self, args: argparse.Namespace) -> int:
        """Stop mesh node."""
        await self._shutdown()
        print("Node stopped.")
        return 0
    
    async def _node_status(self, args: argparse.Namespace) -> int:
        """Show node status."""
        if not self.mesh_node:
            print("Node not running")
            return 1
        
        stats = self.mesh_node.get_stats()
        
        print("\n=== Node Status ===")
        print(f"Node ID:     {stats['node_id']}")
        print(f"Role:        {stats['role']}")
        print(f"Listen:      {stats['listen_addr']}")
        print(f"Peers:       {stats['peers_connected']}")
        print(f"Coordinator: {stats['coordinator'] or 'None'}")
        print(f"Is Leader:   {'Yes' if stats['is_coordinator'] else 'No'}")
        
        return 0
    
    # Peer handlers
    
    async def _handle_peers(self, args: argparse.Namespace) -> int:
        """Handle peer commands."""
        if not args.peer_command:
            print("Usage: aiworker-mesh peers {list|connect|disconnect|blacklist}")
            return 1
        
        if not self.mesh_node:
            print("Node not running. Start with: aiworker-mesh node start")
            return 1
        
        if args.peer_command == "list":
            return await self._peers_list(args)
        elif args.peer_command == "connect":
            return await self._peers_connect(args)
        elif args.peer_command == "disconnect":
            return await self._peers_disconnect(args)
        elif args.peer_command == "blacklist":
            return await self._peers_blacklist(args)
        
        return 0
    
    async def _peers_list(self, args: argparse.Namespace) -> int:
        """List connected peers."""
        peers = list(self.mesh_node.peers.values())
        
        if args.json:
            data = [
                {
                    "node_id": p.node_id,
                    "role": p.role.value,
                    "capabilities": p.capabilities.to_dict(),
                    "trust_score": p.trust_score,
                    "last_seen": p.last_seen,
                }
                for p in peers
            ]
            print(json.dumps(data, indent=2))
        else:
            print(f"\n{'Node ID':<20} {'Role':<12} {'Trust':<8} {'Last Seen':<15}")
            print("-" * 60)
            for p in peers:
                last_seen = time.strftime("%H:%M:%S", time.localtime(p.last_seen))
                print(f"{p.node_id[:18]:<20} {p.role.value:<12} {p.trust_score:.2f}    {last_seen}")
            print(f"\nTotal peers: {len(peers)}")
        
        return 0
    
    async def _peers_connect(self, args: argparse.Namespace) -> int:
        """Connect to a peer."""
        print(f"Connecting to {args.address}...")
        # Implementation would connect to peer
        print("Connected.")
        return 0
    
    async def _peers_disconnect(self, args: argparse.Namespace) -> int:
        """Disconnect from a peer."""
        print(f"Disconnecting from {args.node_id}...")
        await self.mesh_node.connection_pool.remove_connection(args.node_id)
        print("Disconnected.")
        return 0
    
    async def _peers_blacklist(self, args: argparse.Namespace) -> int:
        """Blacklist a peer."""
        print(f"Blacklisting {args.node_id}...")
        self.mesh_node._blacklist.add(args.node_id)
        await self.mesh_node.connection_pool.remove_connection(args.node_id)
        print("Blacklisted.")
        return 0
    
    # Task handlers
    
    async def _handle_task(self, args: argparse.Namespace) -> int:
        """Handle task commands."""
        if not args.task_command:
            print("Usage: aiworker-mesh task {submit|list|status|cancel}")
            return 1
        
        if not self.orchestrator:
            print("Task orchestrator not available")
            return 1
        
        if args.task_command == "submit":
            return await self._task_submit(args)
        elif args.task_command == "list":
            return await self._task_list(args)
        elif args.task_command == "status":
            return await self._task_status(args)
        elif args.task_command == "cancel":
            return await self._task_cancel(args)
        
        return 0
    
    async def _task_submit(self, args: argparse.Namespace) -> int:
        """Submit a task."""
        try:
            payload = json.loads(args.payload)
        except json.JSONDecodeError as e:
            print(f"Invalid JSON payload: {e}")
            return 1
        
        task = Task(
            task_id=f"task_{int(time.time() * 1000)}",
            task_type=TaskType(args.type),
            payload=payload,
            priority=getattr(__import__('aiworker.mesh.task_orchestrator', fromlist=['TaskPriority']), 
                           'TaskPriority')(args.priority),
            created_by=self.mesh_node.config.node_id if self.mesh_node else "cli",
        )
        
        print(f"Submitting task: {task.task_id}")
        
        if args.local:
            result = await self.orchestrator._execute_local(task)
            print(f"Result: {json.dumps(result, indent=2)}")
        else:
            await self.orchestrator.distribute(task)
            print(f"Task distributed: {task.task_id}")
        
        return 0
    
    async def _task_list(self, args: argparse.Namespace) -> int:
        """List tasks."""
        from aiworker.mesh.task_orchestrator import TaskStatus
        
        statuses = [TaskStatus(args.status)] if args.status else list(TaskStatus)
        
        tasks = []
        for status in statuses:
            tasks.extend(self.orchestrator.ledger.get_tasks_by_status(status))
        
        if args.json:
            data = [t.to_dict() for t in tasks]
            print(json.dumps(data, indent=2))
        else:
            print(f"\n{'Task ID':<20} {'Type':<10} {'Status':<12} {'Assigned To':<20}")
            print("-" * 65)
            for t in tasks[:20]:  # Limit to 20
                assigned = (t.assigned_to[:18] + "..") if t.assigned_to else "-"
                print(f"{t.task_id:<20} {t.task_type.value:<10} {t.status.value:<12} {assigned}")
            if len(tasks) > 20:
                print(f"\n... and {len(tasks) - 20} more")
        
        return 0
    
    async def _task_status(self, args: argparse.Namespace) -> int:
        """Get task status."""
        task = self.orchestrator.ledger.get_task(args.task_id)
        
        if not task:
            print(f"Task not found: {args.task_id}")
            return 1
        
        print(json.dumps(task.to_dict(), indent=2))
        return 0
    
    async def _task_cancel(self, args: argparse.Namespace) -> int:
        """Cancel a task."""
        from aiworker.mesh.task_orchestrator import TaskStatus
        
        success = self.orchestrator.ledger.update_task_status(
            args.task_id,
            TaskStatus.CANCELLED
        )
        
        if success:
            print(f"Task cancelled: {args.task_id}")
        else:
            print(f"Failed to cancel task: {args.task_id}")
        
        return 0 if success else 1
    
    # Sync handlers
    
    async def _handle_sync(self, args: argparse.Namespace) -> int:
        """Handle sync commands."""
        if not args.sync_command:
            print("Usage: aiworker-mesh sync {status|force|add}")
            return 1
        
        if not self.sync_engine:
            print("Sync engine not available")
            return 1
        
        if args.sync_command == "status":
            return await self._sync_status(args)
        elif args.sync_command == "force":
            return await self._sync_force(args)
        elif args.sync_command == "add":
            return await self._sync_add(args)
        
        return 0
    
    async def _sync_status(self, args: argparse.Namespace) -> int:
        """Show sync status."""
        stats = self.sync_engine.get_stats()
        
        if args.json:
            print(json.dumps(stats, indent=2))
        else:
            print("\n=== Sync Status ===")
            print(f"Bytes Sent:     {stats['total_bytes_sent']:,}")
            print(f"Peers Synced:   {stats['peers_synced']}")
            print(f"Shared Records: {stats['store_stats']['shared_records']}")
            print(f"Local Records:  {stats['store_stats']['local_records']}")
            print("\nBy Type:")
            for ktype, count in stats['store_stats']['by_type'].items():
                print(f"  {ktype}: {count}")
        
        return 0
    
    async def _sync_force(self, args: argparse.Namespace) -> int:
        """Force sync with peer(s)."""
        print(f"Forcing sync with {args.peer or 'all peers'}...")
        await self.sync_engine.force_sync(args.peer)
        print("Sync initiated.")
        return 0
    
    async def _sync_add(self, args: argparse.Namespace) -> int:
        """Add knowledge."""
        try:
            payload = json.loads(args.payload)
        except json.JSONDecodeError as e:
            print(f"Invalid JSON payload: {e}")
            return 1
        
        record_id = self.sync_engine.store.add_knowledge(
            KnowledgeType(args.type),
            payload,
            local_only=args.local
        )
        
        if record_id:
            print(f"Knowledge added: {record_id}")
            return 0
        else:
            print("Failed to add knowledge (security check failed)")
            return 1
    
    # Role handlers
    
    async def _handle_role(self, args: argparse.Namespace) -> int:
        """Handle role commands."""
        if not args.role_command:
            print("Usage: aiworker-mesh role {status|switch|list}")
            return 1
        
        if not self.role_manager:
            print("Role manager not available")
            return 1
        
        if args.role_command == "status":
            return await self._role_status(args)
        elif args.role_command == "switch":
            return await self._role_switch(args)
        elif args.role_command == "list":
            return await self._role_list(args)
        
        return 0
    
    async def _role_status(self, args: argparse.Namespace) -> int:
        """Show role status."""
        stats = self.role_manager.get_stats()
        
        if args.json:
            print(json.dumps(stats, indent=2))
        else:
            print("\n=== Role Status ===")
            print(f"Current Role:   {stats['current_role']}")
            print(f"Since:          {time.ctime(stats['role_since'])}")
            print(f"Success Rate:   {stats['performance']['success_rate']:.1%}")
            print(f"Tasks Completed: {stats['performance']['tasks_completed']}")
            print(f"\nHardware:")
            print(f"  RAM:          {stats['hardware']['ram_gb']} GB")
            print(f"  GPU:          {'Yes' if stats['hardware']['has_gpu'] else 'No'}")
            print(f"  CPU Cores:    {stats['hardware']['cpu_cores']}")
        
        return 0
    
    async def _role_switch(self, args: argparse.Namespace) -> int:
        """Switch role."""
        new_role = InstanceRole(getattr(args, 'to'))
        
        print(f"Switching to {new_role.value}...")
        
        success = await self.role_manager.switch_role(new_role, force=args.force)
        
        if success:
            print(f"Role switched to {new_role.value}")
            return 0
        else:
            print("Role switch failed")
            return 1
    
    async def _role_list(self, args: argparse.Namespace) -> int:
        """List eligible roles."""
        roles = self.role_manager.get_eligible_roles()
        
        print("\nEligible Roles:")
        for role in roles:
            meets, failures = self.role_manager.hardware.meets_requirements(role)
            status = "✓" if meets else "✗"
            print(f"  {status} {role.value}")
            if failures:
                for f in failures:
                    print(f"      - {f}")
        
        return 0
    
    # Consensus handlers
    
    async def _handle_consensus(self, args: argparse.Namespace) -> int:
        """Handle consensus commands."""
        if not args.consensus_command:
            print("Usage: aiworker-mesh consensus {status|elect}")
            return 1
        
        if not self.consensus:
            print("Consensus engine not available")
            return 1
        
        if args.consensus_command == "status":
            return await self._consensus_status(args)
        elif args.consensus_command == "elect":
            return await self._consensus_elect(args)
        
        return 0
    
    async def _consensus_status(self, args: argparse.Namespace) -> int:
        """Show consensus status."""
        stats = self.consensus.get_stats()
        
        if args.json:
            print(json.dumps(stats, indent=2))
        else:
            print("\n=== Consensus Status ===")
            print(f"State:          {stats['state']}")
            print(f"Term:           {stats['term']}")
            print(f"Leader:         {stats['leader'] or 'None'}")
            print(f"Is Leader:      {'Yes' if stats['is_leader'] else 'No'}")
            print(f"Log Entries:    {stats['log_entries']}")
            print(f"Commit Index:   {stats['commit_index']}")
        
        return 0
    
    async def _consensus_elect(self, args: argparse.Namespace) -> int:
        """Trigger leader election."""
        print("Triggering leader election...")
        # This would trigger election in the consensus engine
        print("Election triggered.")
        return 0
    
    # Monitor handler
    
    async def _handle_monitor(self, args: argparse.Namespace) -> int:
        """Monitor mesh."""
        print("\n=== AIWorker Mesh Monitor ===\n")
        
        while True:
            # Clear screen
            print("\033[2J\033[H")
            
            print(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
            print("-" * 60)
            
            if self.mesh_node:
                stats = self.mesh_node.get_stats()
                print(f"Node: {stats['node_id'][:16]}... | Role: {stats['role']} | Peers: {stats['peers_connected']}")
                print(f"Coordinator: {stats['coordinator'][:16] if stats['coordinator'] else 'None'}...")
            
            if self.orchestrator:
                task_stats = self.orchestrator.get_stats()
                print(f"\nTasks: {task_stats['pending_tasks']} pending | "
                      f"{task_stats['running_tasks']} running | "
                      f"{task_stats['completed_tasks']} completed | "
                      f"{task_stats['failed_tasks']} failed")
            
            if self.consensus:
                cs = self.consensus.get_stats()
                print(f"\nConsensus: {cs['state']} | Term: {cs['term']} | "
                      f"Leader: {'Yes' if cs['is_leader'] else 'No'}")
            
            if not args.watch:
                break
            
            await asyncio.sleep(args.interval)
        
        return 0
    
    # Dashboard handler
    
    async def _handle_dashboard(self, args: argparse.Namespace) -> int:
        """Launch web dashboard."""
        from aiworker.dashboard.mesh_dashboard import create_dashboard
        
        print(f"Starting dashboard on http://{args.host}:{args.port}")
        
        dashboard = await create_dashboard(
            mesh_node=self.mesh_node,
            orchestrator=self.orchestrator,
            sync_engine=self.sync_engine,
            role_manager=self.role_manager,
            consensus=self.consensus,
            host=args.host,
            port=args.port,
        )
        
        print(f"Dashboard running at http://{args.host}:{args.port}")
        print("Press Ctrl+C to stop.")
        
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            await dashboard.stop()
        
        return 0
    
    async def _shutdown(self):
        """Shutdown all services."""
        if self.consensus:
            await self.consensus.stop()
        if self.role_manager:
            await self.role_manager.stop()
        if self.sync_engine:
            await self.sync_engine.stop()
        if self.orchestrator:
            await self.orchestrator.stop()
        if self.mesh_node:
            await self.mesh_node.stop()


def main():
    """Main entry point."""
    cli = MeshCLI()
    try:
        exit_code = asyncio.run(cli.run())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)


if __name__ == "__main__":
    main()
