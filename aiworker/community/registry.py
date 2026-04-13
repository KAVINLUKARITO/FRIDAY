#!/usr/bin/env python3
"""
AIWorker 2.0 — Decentralized Registry
Permissionless registry of AIWorker instances and derivatives.

Usage:
    python registry.py register --type instance --capabilities coding,research
    python registry.py query --capability coding
    python registry.py find-peers --task "web_scraping"
    python registry.py reputation <node-id>
    python registry.py flag <node-id> --reason "safety_violation"
"""

import argparse
import hashlib
import json
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set, Any
from enum import Enum
import base64


class EntryType(Enum):
    """Types of registry entries."""
    INSTANCE = "instance"
    DERIVATIVE = "derivative"
    PLUGIN = "plugin"
    RELEASE = "release"


class Role(Enum):
    """Node roles in mesh."""
    WORKER = "WORKER"
    SPECIALIST = "SPECIALIST"
    COORDINATOR = "COORDINATOR"


class SafetyStatus(Enum):
    """Safety review status."""
    PENDING = "pending"
    COMMUNITY_REVIEWED = "community-reviewed"
    FLAGGED = "flagged"


@dataclass
class RegistryEntry:
    """Base registry entry."""
    id: str  # Ed25519 public key
    type: EntryType
    timestamp: str
    signature: str
    ttl_days: int = 365
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "type": self.type.value,
            "timestamp": self.timestamp,
            "signature": self.signature,
            "ttl_days": self.ttl_days
        }
    
    def is_expired(self) -> bool:
        """Check if entry has expired."""
        entry_time = datetime.fromisoformat(self.timestamp)
        expiry = entry_time + timedelta(days=self.ttl_days)
        return datetime.now() > expiry


@dataclass
class InstanceEntry(RegistryEntry):
    """Running AIWorker node."""
    capabilities: List[str] = None
    role: Role = Role.WORKER
    location_hint: str = ""  # "EU", "US", "APAC"
    mesh_addr: Optional[str] = None
    reputation_score: float = 0.5
    uptime_days: int = 0
    derivative_of: Optional[str] = None
    version: str = "2.0.0"
    
    def __post_init__(self):
        if self.capabilities is None:
            self.capabilities = []
        self.type = EntryType.INSTANCE
    
    def to_dict(self) -> dict:
        base = super().to_dict()
        base.update({
            "capabilities": self.capabilities,
            "role": self.role.value,
            "location_hint": self.location_hint,
            "mesh_addr": self.mesh_addr,
            "reputation_score": self.reputation_score,
            "uptime_days": self.uptime_days,
            "derivative_of": self.derivative_of,
            "version": self.version
        })
        return base


@dataclass
class DerivativeEntry(RegistryEntry):
    """Modified version of AIWorker."""
    name: str = ""
    description: str = ""
    changes_from_canonical: List[str] = None
    safety_review_status: SafetyStatus = SafetyStatus.PENDING
    download_url: str = ""  # IPFS hash or HTTPS
    maintainer: str = ""
    
    def __post_init__(self):
        if self.changes_from_canonical is None:
            self.changes_from_canonical = []
        self.type = EntryType.DERIVATIVE
    
    def to_dict(self) -> dict:
        base = super().to_dict()
        base.update({
            "name": self.name,
            "description": self.description,
            "changes_from_canonical": self.changes_from_canonical,
            "safety_review_status": self.safety_review_status.value,
            "download_url": self.download_url,
            "maintainer": self.maintainer
        })
        return base


@dataclass
class PluginEntry(RegistryEntry):
    """Extension module."""
    name: str = ""
    hook_points: List[str] = None
    sandboxed: bool = True
    
    def __post_init__(self):
        if self.hook_points is None:
            self.hook_points = []
        self.type = EntryType.PLUGIN
    
    def to_dict(self) -> dict:
        base = super().to_dict()
        base.update({
            "name": self.name,
            "hook_points": self.hook_points,
            "sandboxed": self.sandboxed
        })
        return base


@dataclass
class ReleaseEntry(RegistryEntry):
    """Official or unofficial release."""
    version: str = ""
    format: str = ""  # "seed.py", "docker", "airgap"
    hash: str = ""  # SHA-256
    previous_version: Optional[str] = None
    
    def __post_init__(self):
        self.type = EntryType.RELEASE
    
    def to_dict(self) -> dict:
        base = super().to_dict()
        base.update({
            "version": self.version,
            "format": self.format,
            "hash": self.hash,
            "previous_version": self.previous_version
        })
        return base


class FlagEntry:
    """Community flag for moderation."""
    
    def __init__(self, target_id: str, reason: str, evidence: str,
                 reporter_id: str, timestamp: str = None):
        self.target_id = target_id
        self.reason = reason
        self.evidence = evidence
        self.reporter_id = reporter_id
        self.timestamp = timestamp or datetime.now().isoformat()
    
    def to_dict(self) -> dict:
        return {
            "target_id": self.target_id,
            "reason": self.reason,
            "evidence": self.evidence,
            "reporter_id": self.reporter_id,
            "timestamp": self.timestamp
        }


class DHTStorage:
    """Simplified DHT storage backend."""
    
    def __init__(self, storage_path: Path = Path(".registry_dht")):
        self.storage_path = storage_path
        self.storage_path.mkdir(exist_ok=True)
        self._cache: Dict[str, dict] = {}
        self._load_cache()
    
    def _load_cache(self) -> None:
        """Load entries from disk."""
        for entry_file in self.storage_path.glob("*.json"):
            try:
                data = json.loads(entry_file.read_text())
                self._cache[data["id"]] = data
            except:
                pass
    
    def _save_entry(self, entry_id: str, data: dict) -> None:
        """Save entry to disk."""
        entry_path = self.storage_path / f"{entry_id}.json"
        entry_path.write_text(json.dumps(data, indent=2))
    
    def store(self, entry: RegistryEntry) -> bool:
        """Store entry in DHT."""
        data = entry.to_dict()
        self._cache[entry.id] = data
        self._save_entry(entry.id, data)
        return True
    
    def retrieve(self, entry_id: str) -> Optional[dict]:
        """Retrieve entry from DHT."""
        return self._cache.get(entry_id)
    
    def prefix_scan(self, prefix: str) -> List[dict]:
        """Scan for entries with prefix."""
        return [data for eid, data in self._cache.items() if eid.startswith(prefix)]
    
    def get_all(self) -> List[dict]:
        """Get all entries."""
        return list(self._cache.values())
    
    def delete(self, entry_id: str) -> bool:
        """Delete entry from DHT."""
        if entry_id in self._cache:
            del self._cache[entry_id]
            entry_path = self.storage_path / f"{entry_id}.json"
            if entry_path.exists():
                entry_path.unlink()
            return True
        return False


class ReputationEngine:
    """Calculate reputation scores."""
    
    # Weights for reputation factors
    WEIGHTS = {
        "uptime": 0.2,
        "safety": 0.4,
        "endorsements": 0.2,
        "contributions": 0.1,
        "response_time": 0.1
    }
    
    def __init__(self, storage: DHTStorage):
        self.storage = storage
        self._history: Dict[str, List[dict]] = {}
    
    def compute(self, entry_id: str) -> float:
        """Calculate reputation score (0.0-1.0)."""
        entry_data = self.storage.retrieve(entry_id)
        if not entry_data:
            return 0.0
        
        scores = {
            "uptime": self._uptime_score(entry_data),
            "safety": self._safety_score(entry_id),
            "endorsements": self._endorsement_score(entry_id),
            "contributions": self._contribution_score(entry_id),
            "response_time": self._response_score(entry_id)
        }
        
        # Weighted sum
        total = sum(scores[k] * self.WEIGHTS[k] for k in scores)
        
        # Normalize to 0-1
        return min(1.0, max(0.0, total))
    
    def _uptime_score(self, entry_data: dict) -> float:
        """Score based on uptime history."""
        uptime_days = entry_data.get("uptime_days", 0)
        # Score increases with uptime, max at 30 days
        return min(1.0, uptime_days / 30.0)
    
    def _safety_score(self, entry_id: str) -> float:
        """Score based on safety violations."""
        # Check for flags
        flags = self._get_flags(entry_id)
        safety_violations = sum(1 for f in flags if "safety" in f.reason.lower())
        
        if safety_violations > 0:
            return max(0.0, 1.0 - (safety_violations * 0.5))
        return 1.0
    
    def _endorsement_score(self, entry_id: str) -> float:
        """Score based on community endorsements."""
        # Would query endorsements from DHT
        # For now, return neutral
        return 0.5
    
    def _contribution_score(self, entry_id: str) -> float:
        """Score based on code contributions."""
        # Would track contributions
        return 0.5
    
    def _response_score(self, entry_id: str) -> float:
        """Score based on response time to peers."""
        # Would measure response times
        return 0.5
    
    def _get_flags(self, entry_id: str) -> List[FlagEntry]:
        """Get flags for entry."""
        # Would load from storage
        return []


class Registry:
    """Main registry interface."""
    
    FLAG_THRESHOLD = 3  # Flags from high-rep nodes to hide entry
    
    def __init__(self, storage_path: Path = Path(".registry_dht")):
        self.storage = DHTStorage(storage_path)
        self.reputation = ReputationEngine(self.storage)
        self._flags: Dict[str, List[FlagEntry]] = {}
    
    def register(self, entry: RegistryEntry) -> bool:
        """Register a new entry."""
        # Verify signature (would do proper Ed25519 verification)
        if not self._verify_signature(entry):
            print("Signature verification failed")
            return False
        
        # Store in DHT
        return self.storage.store(entry)
    
    def _verify_signature(self, entry: RegistryEntry) -> bool:
        """Verify entry signature."""
        # In production: Ed25519 signature verification
        # For now, accept all valid-format signatures
        return len(entry.signature) >= 64 and all(c in '0123456789abcdef' for c in entry.signature[:64])
    
    def query(self, entry_type: Optional[EntryType] = None,
              capabilities: Optional[List[str]] = None,
              min_reputation: float = 0.5,
              location_hint: Optional[str] = None,
              limit: int = 20) -> List[dict]:
        """Search registry with filters."""
        results = []
        
        for entry_data in self.storage.get_all():
            # Filter by type
            if entry_type and entry_data.get("type") != entry_type.value:
                continue
            
            # Filter by capabilities
            if capabilities:
                entry_caps = set(entry_data.get("capabilities", []))
                if not any(cap in entry_caps for cap in capabilities):
                    continue
            
            # Filter by reputation
            entry_id = entry_data["id"]
            rep_score = self.reputation.compute(entry_id)
            if rep_score < min_reputation:
                continue
            
            # Filter by location
            if location_hint and entry_data.get("location_hint") != location_hint:
                continue
            
            # Add reputation to result
            entry_data["computed_reputation"] = rep_score
            results.append(entry_data)
        
        # Sort by reputation
        results.sort(key=lambda x: x.get("computed_reputation", 0), reverse=True)
        
        return results[:limit]
    
    def find_peers_for_task(self, task_requirements: dict) -> List[dict]:
        """Discovery for mesh joining."""
        required_caps = task_requirements.get("capabilities", [])
        
        # Query instances with matching capabilities
        instances = self.query(
            entry_type=EntryType.INSTANCE,
            capabilities=required_caps,
            min_reputation=0.6
        )
        
        # Filter: Accepting peers, compatible version
        accepting = []
        for inst in instances:
            if inst.get("mesh_addr"):  # Has mesh address
                # Check version compatibility
                version = inst.get("version", "2.0.0")
                if version.startswith("2."):  # Major version compatible
                    accepting.append(inst)
        
        # Sort by latency estimate (geographic hint)
        accepting.sort(key=lambda x: x.get("reputation_score", 0), reverse=True)
        
        return accepting
    
    def find_derivative_for_use_case(self, use_case: str) -> Optional[dict]:
        """Find specialized version."""
        use_case_lower = use_case.lower()
        
        derivatives = self.query(entry_type=EntryType.DERIVATIVE)
        
        best_match = None
        best_score = 0
        
        for deriv in derivatives:
            # Keyword match on description and changes
            description = deriv.get("description", "").lower()
            changes = " ".join(deriv.get("changes_from_canonical", [])).lower()
            text = f"{description} {changes}"
            
            # Simple keyword matching
            keywords = use_case_lower.split()
            score = sum(1 for kw in keywords if kw in text)
            
            # Prioritize reviewed
            if deriv.get("safety_review_status") == "community-reviewed":
                score += 2
            
            # Check maintainer activity (would check timestamp)
            
            if score > best_score:
                best_score = score
                best_match = deriv
        
        return best_match
    
    def flag_entry(self, target_id: str, reason: str, evidence: str,
                   reporter_id: str) -> bool:
        """Community moderation - flag an entry."""
        flag = FlagEntry(target_id, reason, evidence, reporter_id)
        
        if target_id not in self._flags:
            self._flags[target_id] = []
        
        self._flags[target_id].append(flag)
        
        # Check threshold
        flags = self._flags[target_id]
        high_rep_flags = sum(1 for f in flags 
                           if self.reputation.compute(f.reporter_id) > 0.7)
        
        if high_rep_flags >= self.FLAG_THRESHOLD:
            print(f"Entry {target_id} flagged - hidden from default view")
            # Would update entry visibility in DHT
        
        return True
    
    def renew_entry(self, entry_id: str, private_key: str) -> bool:
        """Extend TTL, update timestamp."""
        entry_data = self.storage.retrieve(entry_id)
        if not entry_data:
            return False
        
        # Update timestamp
        entry_data["timestamp"] = datetime.now().isoformat()
        
        # Sign new timestamp (would use private_key properly)
        entry_data["signature"] = self._sign(entry_data, private_key)
        
        # Store updated entry
        self.storage.store(self._dict_to_entry(entry_data))
        return True
    
    def revoke_entry(self, entry_id: str, reason: str, private_key: str) -> bool:
        """Creator-requested removal."""
        entry_data = self.storage.retrieve(entry_id)
        if not entry_data:
            return False
        
        # Verify creator signature
        if not self._verify_creator(entry_id, private_key):
            return False
        
        # Mark as revoked
        entry_data["revoked"] = True
        entry_data["revocation_reason"] = reason
        entry_data["revocation_time"] = datetime.now().isoformat()
        
        self.storage.store(self._dict_to_entry(entry_data))
        return True
    
    def prune_expired(self) -> int:
        """Remove entries past TTL with no renewal."""
        removed = 0
        for entry_data in self.storage.get_all():
            entry = self._dict_to_entry(entry_data)
            if entry and entry.is_expired():
                self.storage.delete(entry.id)
                removed += 1
        return removed
    
    def _sign(self, data: dict, private_key: str) -> str:
        """Sign data (placeholder)."""
        # In production: Ed25519 signing
        data_str = json.dumps(data, sort_keys=True)
        return hashlib.sha256(f"{data_str}{private_key}".encode()).hexdigest()
    
    def _verify_creator(self, entry_id: str, private_key: str) -> bool:
        """Verify creator owns entry."""
        # In production: Verify signature with public key
        return True
    
    def _dict_to_entry(self, data: dict) -> Optional[RegistryEntry]:
        """Convert dict to appropriate entry type."""
        entry_type = data.get("type")
        
        if entry_type == EntryType.INSTANCE.value:
            return InstanceEntry(
                id=data["id"],
                type=EntryType.INSTANCE,
                timestamp=data["timestamp"],
                signature=data["signature"],
                ttl_days=data.get("ttl_days", 365),
                capabilities=data.get("capabilities", []),
                role=Role(data.get("role", "WORKER")),
                location_hint=data.get("location_hint", ""),
                mesh_addr=data.get("mesh_addr"),
                reputation_score=data.get("reputation_score", 0.5),
                uptime_days=data.get("uptime_days", 0),
                derivative_of=data.get("derivative_of"),
                version=data.get("version", "2.0.0")
            )
        elif entry_type == EntryType.DERIVATIVE.value:
            return DerivativeEntry(
                id=data["id"],
                type=EntryType.DERIVATIVE,
                timestamp=data["timestamp"],
                signature=data["signature"],
                ttl_days=data.get("ttl_days", 365),
                name=data.get("name", ""),
                description=data.get("description", ""),
                changes_from_canonical=data.get("changes_from_canonical", []),
                safety_review_status=SafetyStatus(data.get("safety_review_status", "pending")),
                download_url=data.get("download_url", ""),
                maintainer=data.get("maintainer", "")
            )
        # Add other types...
        return None


class RegistryCLI:
    """Command-line interface for registry."""
    
    def __init__(self, registry: Registry = None):
        self.registry = registry or Registry()
    
    def register_instance(self, node_id: str, capabilities: List[str],
                          role: str, location: str, mesh_addr: str,
                          version: str, signature: str) -> None:
        """Register an instance."""
        entry = InstanceEntry(
            id=node_id,
            type=EntryType.INSTANCE,
            timestamp=datetime.now().isoformat(),
            signature=signature,
            capabilities=capabilities,
            role=Role(role),
            location_hint=location,
            mesh_addr=mesh_addr,
            version=version
        )
        
        if self.registry.register(entry):
            print(f"Registered instance: {node_id}")
        else:
            print("Registration failed")
    
    def query_registry(self, entry_type: str = None, capabilities: str = None,
                       min_reputation: float = 0.5, limit: int = 20) -> None:
        """Query registry."""
        caps = capabilities.split(",") if capabilities else None
        etype = EntryType(entry_type) if entry_type else None
        
        results = self.registry.query(
            entry_type=etype,
            capabilities=caps,
            min_reputation=min_reputation,
            limit=limit
        )
        
        print(f"\nFound {len(results)} entries:")
        print("="*70)
        
        for entry in results:
            print(f"\nID: {entry['id']}")
            print(f"  Type: {entry['type']}")
            print(f"  Reputation: {entry.get('computed_reputation', 0):.2f}")
            if 'capabilities' in entry:
                print(f"  Capabilities: {', '.join(entry['capabilities'])}")
            if 'mesh_addr' in entry:
                print(f"  Mesh: {entry['mesh_addr']}")
        
        print("="*70)
    
    def find_peers(self, task: str) -> None:
        """Find peers for task."""
        requirements = {"capabilities": task.split()}
        peers = self.registry.find_peers_for_task(requirements)
        
        print(f"\nFound {len(peers)} compatible peers:")
        print("="*70)
        
        for peer in peers:
            print(f"\n{peer['id']}")
            print(f"  Address: {peer.get('mesh_addr', 'N/A')}")
            print(f"  Capabilities: {', '.join(peer.get('capabilities', []))}")
            print(f"  Reputation: {peer.get('reputation_score', 0):.2f}")
        
        print("="*70)
    
    def show_reputation(self, node_id: str) -> None:
        """Show reputation for node."""
        score = self.registry.reputation.compute(node_id)
        
        print(f"\nReputation for {node_id}:")
        print(f"  Overall Score: {score:.2f} / 1.0")
        
        # Show breakdown
        entry = self.registry.storage.retrieve(node_id)
        if entry:
            print(f"  Uptime: {entry.get('uptime_days', 0)} days")
            print(f"  Version: {entry.get('version', 'unknown')}")
            print(f"  Role: {entry.get('role', 'unknown')}")
    
    def flag_node(self, node_id: str, reason: str, evidence: str,
                  reporter_id: str) -> None:
        """Flag a node."""
        if self.registry.flag_entry(node_id, reason, evidence, reporter_id):
            print(f"Flagged {node_id} for: {reason}")
        else:
            print("Flagging failed")


def main():
    parser = argparse.ArgumentParser(description="AIWorker Decentralized Registry")
    subparsers = parser.add_subparsers(dest="command")
    
    # Register
    register_parser = subparsers.add_parser("register", help="Register entry")
    register_parser.add_argument("--type", required=True, choices=["instance", "derivative", "plugin", "release"])
    register_parser.add_argument("--id", required=True, help="Entry ID (public key)")
    register_parser.add_argument("--capabilities", help="Comma-separated capabilities")
    register_parser.add_argument("--role", default="WORKER", choices=["WORKER", "SPECIALIST", "COORDINATOR"])
    register_parser.add_argument("--location", help="Location hint (EU/US/APAC)")
    register_parser.add_argument("--mesh-addr", help="Mesh network address")
    register_parser.add_argument("--version", default="2.0.0")
    register_parser.add_argument("--signature", required=True, help="Ed25519 signature")
    
    # Query
    query_parser = subparsers.add_parser("query", help="Query registry")
    query_parser.add_argument("--type", choices=["instance", "derivative", "plugin", "release"])
    query_parser.add_argument("--capability", help="Required capability")
    query_parser.add_argument("--min-reputation", type=float, default=0.5)
    query_parser.add_argument("--limit", type=int, default=20)
    
    # Find peers
    peers_parser = subparsers.add_parser("find-peers", help="Find peers for task")
    peers_parser.add_argument("--task", required=True, help="Task requirements")
    
    # Reputation
    rep_parser = subparsers.add_parser("reputation", help="Show reputation")
    rep_parser.add_argument("node_id", help="Node ID")
    
    # Flag
    flag_parser = subparsers.add_parser("flag", help="Flag entry")
    flag_parser.add_argument("node_id", help="Target node ID")
    flag_parser.add_argument("--reason", required=True, help="Flag reason")
    flag_parser.add_argument("--evidence", help="Evidence URL/text")
    flag_parser.add_argument("--reporter", required=True, help="Your node ID")
    
    # Prune
    prune_parser = subparsers.add_parser("prune", help="Remove expired entries")
    
    args = parser.parse_args()
    
    registry = Registry()
    cli = RegistryCLI(registry)
    
    if args.command == "register":
        caps = args.capabilities.split(",") if args.capabilities else []
        cli.register_instance(
            args.id, caps, args.role, args.location or "",
            args.mesh_addr or "", args.version, args.signature
        )
    elif args.command == "query":
        cli.query_registry(args.type, args.capability, args.min_reputation, args.limit)
    elif args.command == "find-peers":
        cli.find_peers(args.task)
    elif args.command == "reputation":
        cli.show_reputation(args.node_id)
    elif args.command == "flag":
        cli.flag_node(args.node_id, args.reason, args.evidence or "", args.reporter)
    elif args.command == "prune":
        removed = registry.prune_expired()
        print(f"Pruned {removed} expired entries")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

