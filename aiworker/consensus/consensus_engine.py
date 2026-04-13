#!/usr/bin/env python3
"""
AIWorker Consensus Engine - Distributed Consensus for Leader Election
Phase 5: Ecosystem Expansion & Multi-Instance Coordination

Implements Raft-inspired consensus for coordinator election and distributed
decision making across the AIWorker mesh. Handles network partitions,
leader failures, and ensures consistency.
"""

import asyncio
import hashlib
import json
import logging
import random
import time
from dataclasses import dataclass, field, asdict
from enum import Enum, auto
from typing import Dict, List, Optional, Set, Callable, Any, Tuple
from collections import defaultdict

from aiworker.mesh.network_node import MeshNode, MeshMessage, MessageType, NodeRole

logger = logging.getLogger("aiworker.consensus.engine")


class NodeState(Enum):
    """Raft node states."""
    FOLLOWER = "follower"
    CANDIDATE = "candidate"
    LEADER = "leader"


class ConsensusEvent(Enum):
    """Consensus events that can be subscribed to."""
    ELECTION_START = auto()
    ELECTION_WON = auto()
    LEADER_DISCOVERED = auto()
    LEADER_LOST = auto()
    TERM_CHANGED = auto()
    MEMBERSHIP_CHANGED = auto()


@dataclass
class LogEntry:
    """A single entry in the distributed log."""
    index: int
    term: int
    command: Dict[str, Any]
    committed: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "term": self.term,
            "command": self.command,
            "committed": self.committed,
        }


@dataclass
class VoteRequest:
    """Request for votes during election."""
    term: int
    candidate_id: str
    last_log_index: int
    last_log_term: int


@dataclass
class VoteResponse:
    """Response to vote request."""
    term: int
    voter_id: str
    vote_granted: bool


@dataclass
class AppendEntries:
    """Leader heartbeat and log replication."""
    term: int
    leader_id: str
    prev_log_index: int
    prev_log_term: int
    entries: List[LogEntry]
    leader_commit: int


@dataclass
class AppendResponse:
    """Response to append entries."""
    term: int
    follower_id: str
    success: bool
    match_index: int


class DistributedLog:
    """Replicated log for consensus."""
    
    def __init__(self):
        self.entries: List[LogEntry] = []
        self.commit_index = 0
        self._lock = asyncio.Lock()
    
    async def append(self, entry: LogEntry) -> int:
        """Append entry to log."""
        async with self._lock:
            entry.index = len(self.entries) + 1
            self.entries.append(entry)
            return entry.index
    
    async def get(self, index: int) -> Optional[LogEntry]:
        """Get entry at index."""
        async with self._lock:
            if 1 <= index <= len(self.entries):
                return self.entries[index - 1]
            return None
    
    async def get_last(self) -> Tuple[int, int]:
        """Get last log index and term."""
        async with self._lock:
            if not self.entries:
                return 0, 0
            last = self.entries[-1]
            return last.index, last.term
    
    async def truncate_from(self, index: int):
        """Truncate log from index onwards."""
        async with self._lock:
            if 1 <= index <= len(self.entries):
                self.entries = self.entries[:index - 1]
    
    async def commit(self, index: int):
        """Mark entries up to index as committed."""
        async with self._lock:
            for entry in self.entries:
                if entry.index <= index:
                    entry.committed = True
            self.commit_index = max(self.commit_index, index)
    
    def get_committed(self) -> List[LogEntry]:
        """Get all committed entries."""
        return [e for e in self.entries if e.committed]


class ConsensusEngine:
    """
    Raft-inspired consensus engine for AIWorker mesh.
    
    Features:
    - Leader election with randomized timeouts
    - Log replication for distributed decisions
    - Automatic failover on leader failure
    - Network partition tolerance
    - Term-based consistency
    """
    
    # Timing constants (in seconds)
    MIN_ELECTION_TIMEOUT = 0.15
    MAX_ELECTION_TIMEOUT = 0.30
    HEARTBEAT_INTERVAL = 0.05
    
    def __init__(self, mesh_node: MeshNode):
        self.mesh_node = mesh_node
        self.node_id = mesh_node.config.node_id
        
        # Raft state
        self.state = NodeState.FOLLOWER
        self.current_term = 0
        self.voted_for: Optional[str] = None
        self.log = DistributedLog()
        
        # Leader state
        self.leader_id: Optional[str] = None
        self.next_index: Dict[str, int] = {}
        self.match_index: Dict[str, int] = {}
        
        # Volatile state
        self.last_heartbeat = time.time()
        self.election_timeout = self._random_timeout()
        
        # Vote tracking
        self.votes_received: Set[str] = set()
        
        # Background tasks
        self._tasks: List[asyncio.Task] = []
        self._running = False
        
        # Event callbacks
        self._event_callbacks: Dict[ConsensusEvent, List[Callable]] = {
            event: [] for event in ConsensusEvent
        }
        
        # Register handlers
        self._register_handlers()
        
        logger.info("ConsensusEngine initialized")
    
    def _random_timeout(self) -> float:
        """Generate random election timeout."""
        return random.uniform(
            self.MIN_ELECTION_TIMEOUT,
            self.MAX_ELECTION_TIMEOUT
        )
    
    def _register_handlers(self):
        """Register mesh message handlers."""
        self.mesh_node.register_handler(
            MessageType.COORDINATOR_ELECT,
            self._handle_vote_request
        )
        self.mesh_node.register_handler(
            MessageType.COORDINATOR_ACCEPT,
            self._handle_vote_response
        )
        # Use SYNC_REQUEST/SYNC_RESPONSE for AppendEntries
        self.mesh_node.register_handler(
            MessageType.SYNC_REQUEST,
            self._handle_append_entries
        )
    
    async def start(self):
        """Start the consensus engine."""
        self._running = True
        
        # Start election monitor
        self._tasks.append(asyncio.create_task(self._election_monitor()))
        
        # Start heartbeat if leader
        if self.state == NodeState.LEADER:
            self._tasks.append(asyncio.create_task(self._heartbeat_loop()))
        
        logger.info("ConsensusEngine started")
    
    async def stop(self):
        """Stop the consensus engine."""
        self._running = False
        
        for task in self._tasks:
            task.cancel()
        
        logger.info("ConsensusEngine stopped")
    
    async def _election_monitor(self):
        """Monitor for election timeout."""
        while self._running:
            try:
                await asyncio.sleep(0.01)  # 10ms check interval
                
                if self.state == NodeState.LEADER:
                    continue
                
                # Check if election timeout elapsed
                elapsed = time.time() - self.last_heartbeat
                
                if elapsed > self.election_timeout:
                    await self._start_election()
                    
            except Exception as e:
                logger.error(f"Election monitor error: {e}")
    
    async def _start_election(self):
        """Start leader election."""
        self.state = NodeState.CANDIDATE
        self.current_term += 1
        self.voted_for = self.node_id
        self.votes_received = {self.node_id}
        self.election_timeout = self._random_timeout()
        
        logger.info(f"Starting election for term {self.current_term}")
        
        await self._emit_event(ConsensusEvent.ELECTION_START, {
            "term": self.current_term
        })
        
        # Request votes from all peers
        last_index, last_term = await self.log.get_last()
        
        message = MeshMessage(
            msg_type=MessageType.COORDINATOR_ELECT,
            sender_id=self.node_id,
            payload={
                "type": "vote_request",
                "term": self.current_term,
                "candidate_id": self.node_id,
                "last_log_index": last_index,
                "last_log_term": last_term,
            }
        )
        
        await self.mesh_node.broadcast(message)
        
        # Wait for votes
        await asyncio.sleep(self.election_timeout)
        
        # Check if we won
        if self.state == NodeState.CANDIDATE:
            quorum = (len(self.mesh_node.peers) + 1) // 2 + 1
            
            if len(self.votes_received) >= quorum:
                await self._become_leader()
            else:
                logger.info(f"Election lost, received {len(self.votes_received)} votes")
                self.state = NodeState.FOLLOWER
                self.voted_for = None
    
    async def _become_leader(self):
        """Transition to leader state."""
        self.state = NodeState.LEADER
        self.leader_id = self.node_id
        
        # Initialize leader state
        last_index, _ = await self.log.get_last()
        for peer_id in self.mesh_node.peers:
            self.next_index[peer_id] = last_index + 1
            self.match_index[peer_id] = 0
        
        logger.info(f"Became leader for term {self.current_term}")
        
        await self._emit_event(ConsensusEvent.ELECTION_WON, {
            "term": self.current_term
        })
        
        # Start heartbeat
        self._tasks.append(asyncio.create_task(self._heartbeat_loop()))
        
        # Update mesh node
        self.mesh_node._coordinator_id = self.node_id
        self.mesh_node.role = NodeRole.COORDINATOR
    
    async def _heartbeat_loop(self):
        """Send periodic heartbeats as leader."""
        while self._running and self.state == NodeState.LEADER:
            try:
                await self._send_heartbeat()
                await asyncio.sleep(self.HEARTBEAT_INTERVAL)
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
    
    async def _send_heartbeat(self):
        """Send heartbeat to all followers."""
        last_index, _ = await self.log.get_last()
        
        message = MeshMessage(
            msg_type=MessageType.SYNC_REQUEST,
            sender_id=self.node_id,
            payload={
                "type": "append_entries",
                "term": self.current_term,
                "leader_id": self.node_id,
                "prev_log_index": last_index,
                "prev_log_term": self.current_term,
                "entries": [],
                "leader_commit": self.log.commit_index,
            }
        )
        
        await self.mesh_node.broadcast(message)
    
    async def _handle_vote_request(self, message: MeshMessage, protocol):
        """Handle vote request from candidate."""
        payload = message.payload
        
        if payload.get("type") != "vote_request":
            return
        
        term = payload["term"]
        candidate_id = payload["candidate_id"]
        last_log_index = payload["last_log_index"]
        last_log_term = payload["last_log_term"]
        
        # Reply with vote response
        vote_granted = False
        
        # If term > current, update term and become follower
        if term > self.current_term:
            self.current_term = term
            self.state = NodeState.FOLLOWER
            self.voted_for = None
            await self._emit_event(ConsensusEvent.TERM_CHANGED, {
                "term": term
            })
        
        # Grant vote if:
        # 1. Term >= current
        # 2. Haven't voted or voted for this candidate
        # 3. Candidate's log is at least as up-to-date
        if term >= self.current_term:
            my_last_index, my_last_term = await self.log.get_last()
            
            log_ok = (last_log_term > my_last_term or
                     (last_log_term == my_last_term and
                      last_log_index >= my_last_index))
            
            vote_ok = self.voted_for is None or self.voted_for == candidate_id
            
            if log_ok and vote_ok:
                vote_granted = True
                self.voted_for = candidate_id
                self.last_heartbeat = time.time()
        
        # Send response
        response = MeshMessage(
            msg_type=MessageType.COORDINATOR_ACCEPT,
            sender_id=self.node_id,
            payload={
                "type": "vote_response",
                "term": self.current_term,
                "voter_id": self.node_id,
                "vote_granted": vote_granted,
                "candidate_id": candidate_id,
            }
        )
        
        await self.mesh_node.send_to(candidate_id, response)
    
    async def _handle_vote_response(self, message: MeshMessage, protocol):
        """Handle vote response."""
        payload = message.payload
        
        if payload.get("type") != "vote_response":
            return
        
        if self.state != NodeState.CANDIDATE:
            return
        
        term = payload["term"]
        voter_id = payload["voter_id"]
        vote_granted = payload["vote_granted"]
        
        # Update term if needed
        if term > self.current_term:
            self.current_term = term
            self.state = NodeState.FOLLOWER
            self.voted_for = None
            return
        
        # Record vote
        if vote_granted:
            self.votes_received.add(voter_id)
            logger.debug(f"Received vote from {voter_id}")
    
    async def _handle_append_entries(self, message: MeshMessage, protocol):
        """Handle append entries (heartbeat) from leader."""
        payload = message.payload
        
        if payload.get("type") != "append_entries":
            return
        
        term = payload["term"]
        leader_id = payload["leader_id"]
        prev_log_index = payload["prev_log_index"]
        prev_log_term = payload["prev_log_term"]
        entries_data = payload.get("entries", [])
        leader_commit = payload["leader_commit"]
        
        # Reset heartbeat timer
        self.last_heartbeat = time.time()
        
        # If term < current, reject
        if term < self.current_term:
            await self._send_append_response(leader_id, False, 0)
            return
        
        # Update term and become follower if needed
        if term > self.current_term:
            self.current_term = term
            self.state = NodeState.FOLLOWER
            self.voted_for = None
            await self._emit_event(ConsensusEvent.TERM_CHANGED, {"term": term})
        
        # Update leader
        if self.leader_id != leader_id:
            self.leader_id = leader_id
            await self._emit_event(ConsensusEvent.LEADER_DISCOVERED, {
                "leader_id": leader_id
            })
        
        # Check log consistency
        if prev_log_index > 0:
            prev_entry = await self.log.get(prev_log_index)
            if not prev_entry or prev_entry.term != prev_log_term:
                await self._send_append_response(leader_id, False, 0)
                return
        
        # Append new entries
        for entry_data in entries_data:
            entry = LogEntry(
                index=entry_data["index"],
                term=entry_data["term"],
                command=entry_data["command"],
            )
            await self.log.append(entry)
        
        # Update commit index
        if leader_commit > self.log.commit_index:
            await self.log.commit(min(leader_commit, await self.log.get_last()[0]))
        
        # Send success response
        last_index, _ = await self.log.get_last()
        await self._send_append_response(leader_id, True, last_index)
    
    async def _send_append_response(self, leader_id: str, success: bool, match_index: int):
        """Send append entries response."""
        response = MeshMessage(
            msg_type=MessageType.SYNC_RESPONSE,
            sender_id=self.node_id,
            payload={
                "type": "append_response",
                "term": self.current_term,
                "follower_id": self.node_id,
                "success": success,
                "match_index": match_index,
            }
        )
        
        await self.mesh_node.send_to(leader_id, response)
    
    async def propose(self, command: Dict[str, Any]) -> Optional[int]:
        """
        Propose a command to the distributed log.
        
        Returns:
            Log index if proposal was accepted, None otherwise
        """
        if self.state != NodeState.LEADER:
            # Forward to leader
            if self.leader_id:
                message = MeshMessage(
                    msg_type=MessageType.SYNC_REQUEST,
                    sender_id=self.node_id,
                    payload={
                        "type": "client_request",
                        "command": command,
                    }
                )
                await self.mesh_node.send_to(self.leader_id, message)
                return None
            else:
                raise Exception("No leader available")
        
        # Append to local log
        entry = LogEntry(
            term=self.current_term,
            command=command,
        )
        index = await self.log.append(entry)
        
        # Replicate to followers
        await self._replicate_log()
        
        return index
    
    async def _replicate_log(self):
        """Replicate log entries to followers."""
        for peer_id in self.mesh_node.peers:
            asyncio.create_task(self._replicate_to_peer(peer_id))
    
    async def _replicate_to_peer(self, peer_id: str):
        """Replicate log to a specific peer."""
        next_idx = self.next_index.get(peer_id, 1)
        
        # Get entries to send
        entries = []
        last_index, _ = await self.log.get_last()
        
        for i in range(next_idx, last_index + 1):
            entry = await self.log.get(i)
            if entry:
                entries.append(entry.to_dict())
        
        if not entries:
            return
        
        # Get prev log info
        prev_index = next_idx - 1
        prev_term = 0
        if prev_index > 0:
            prev_entry = await self.log.get(prev_index)
            if prev_entry:
                prev_term = prev_entry.term
        
        message = MeshMessage(
            msg_type=MessageType.SYNC_REQUEST,
            sender_id=self.node_id,
            payload={
                "type": "append_entries",
                "term": self.current_term,
                "leader_id": self.node_id,
                "prev_log_index": prev_index,
                "prev_log_term": prev_term,
                "entries": entries,
                "leader_commit": self.log.commit_index,
            }
        )
        
        await self.mesh_node.send_to(peer_id, message)
    
    def is_leader(self) -> bool:
        """Check if this node is the leader."""
        return self.state == NodeState.LEADER
    
    def get_leader(self) -> Optional[str]:
        """Get current leader ID."""
        return self.leader_id
    
    async def _emit_event(self, event: ConsensusEvent, data: Dict[str, Any]):
        """Emit consensus event."""
        for callback in self._event_callbacks.get(event, []):
            try:
                await callback(event, data)
            except Exception as e:
                logger.error(f"Event callback error: {e}")
    
    def on_event(self, event: ConsensusEvent, callback: Callable):
        """Register event callback."""
        self._event_callbacks[event].append(callback)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get consensus statistics."""
        return {
            "state": self.state.value,
            "term": self.current_term,
            "leader": self.leader_id,
            "is_leader": self.is_leader(),
            "log_entries": len(self.log.entries),
            "commit_index": self.log.commit_index,
            "voted_for": self.voted_for,
        }


# Convenience functions
async def create_consensus_engine(mesh_node: MeshNode) -> ConsensusEngine:
    """Create and start a consensus engine."""
    engine = ConsensusEngine(mesh_node)
    await engine.start()
    return engine
