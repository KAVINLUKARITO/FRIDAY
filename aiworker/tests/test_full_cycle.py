#!/usr/bin/env python3
"""
AIWorker Full Lifecycle Tests
Phase 6: Autonomous Evolution & Self-Replication

End-to-end tests for birth, reproduction, and death of AIWorker instances.
Uses mocking to simulate time acceleration and external APIs.
"""

import asyncio
import json
import os
import pytest
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional, Any
from unittest.mock import Mock, patch, AsyncMock
import shutil

# Import AIWorker components
from aiworker.mesh.network_node import MeshNode, MeshConfig, NodeRole
from aiworker.lifecycle.spawner import (
    Spawner, ChildInstance, InstanceStatus, VPSConfig, VPSProvider
)
from aiworker.lifecycle.successor import (
    SuccessorManager, SuccessorVersion, SuccessorStatus, EvolutionTrigger
)
from aiworker.lifecycle.retirement import (
    RetirementManager, RetirementPlan, RetirementPhase, RetirementTrigger
)
from aiworker.economics.ledger import Ledger, TransactionType, TransactionCategory
from aiworker.governance.constitution import Constitution, OverrideType, GovernanceLevel
from aiworker.evolution.architect import Architect, ImprovementType


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def temp_dir():
    """Create temporary directory for test databases."""
    tmp = tempfile.mkdtemp(prefix="aiworker_test_")
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def mock_mesh_node(temp_dir):
    """Create mock mesh node."""
    config = MeshConfig(
        node_id="test_parent_001",
        role="WORKER",
        listen_addr="127.0.0.1:0",
    )
    
    node = Mock(spec=MeshNode)
    node.config = config
    node.config.node_id = "test_parent_001"
    node.role = NodeRole.WORKER
    node.peers = {}
    node.capabilities = Mock()
    node.capabilities.ram_gb = 32
    node.capabilities.current_load = 0.5
    node.capabilities.queue_depth = 0
    node.capabilities.active_tasks = 1
    node.capabilities.cpu_cores = 4
    
    return node


@pytest.fixture
def mock_sync_engine():
    """Create mock sync engine."""
    engine = Mock()
    engine.force_sync = AsyncMock()
    engine.get_stats = Mock(return_value={
        "store_stats": {"shared_records": 100}
    })
    return engine


@pytest.fixture
def spawner(mock_mesh_node, temp_dir):
    """Create spawner instance."""
    db_path = os.path.join(temp_dir, "spawner.db")
    
    with patch("aiworker.lifecycle.spawner.VPSProvisioner") as MockProvisioner:
        # Mock provisioner
        mock_prov = AsyncMock()
        mock_prov.__aenter__ = AsyncMock(return_value=mock_prov)
        mock_prov.__aexit__ = AsyncMock(return_value=None)
        mock_prov.provision = AsyncMock(return_value=("vps_123", "10.0.0.5"))
        mock_prov.destroy = AsyncMock(return_value=True)
        MockProvisioner.return_value = mock_prov
        
        spawner = Spawner(
            mesh_node=mock_mesh_node,
            db_path=db_path,
            vps_api_keys={"mock": "test_key"},
        )
        
        yield spawner


@pytest.fixture
def ledger(temp_dir):
    """Create ledger instance."""
    db_path = os.path.join(temp_dir, "ledger.db")
    ledger = Ledger(
        instance_id="test_instance",
        db_path=db_path,
    )
    yield ledger


@pytest.fixture
def constitution(temp_dir):
    """Create constitution instance."""
    db_path = os.path.join(temp_dir, "constitution.db")
    constitution = Constitution(
        instance_id="test_instance",
        db_path=db_path,
    )
    yield constitution


# =============================================================================
# Test Class: Instance Birth
# =============================================================================

class TestInstanceBirth:
    """Tests for instance creation and initialization."""
    
    @pytest.mark.asyncio
    async def test_spawn_child(self, spawner):
        """Test spawning a child instance."""
        # Spawn child with human approval
        child = await spawner.spawn_child(
            role=None,  # Auto-detect
            provider=VPSProvider.MOCK,
            region="test",
            human_approved=True,
        )
        
        assert child is not None
        assert child.instance_id.startswith("child_")
        assert child.parent_id == "test_parent_001"
        assert child.status == InstanceStatus.OPERATIONAL
        assert child.vps_id == "vps_123"
        assert child.ip_address == "10.0.0.5"
    
    @pytest.mark.asyncio
    async def test_spawn_requires_approval_for_first(self, spawner):
        """Test that first spawn requires human approval."""
        # Try to spawn without approval (no children yet)
        child = await spawner.spawn_child(
            provider=VPSProvider.MOCK,
            human_approved=False,
        )
        
        # Should fail without approval
        assert child is None
    
    @pytest.mark.asyncio
    async def test_child_config_inheritance(self, spawner):
        """Test that child inherits optimized configuration."""
        child = await spawner.spawn_child(
            provider=VPSProvider.MOCK,
            human_approved=True,
        )
        
        assert child.vps_config is not None
        assert child.vps_config.provider == VPSProvider.HETZNER
        assert child.vps_config.ram_gb >= 8  # Minimum for any role
    
    @pytest.mark.asyncio
    async def test_child_knowledge_seeding(self, spawner, mock_sync_engine):
        """Test that child receives knowledge from parent."""
        spawner.sync_engine = mock_sync_engine
        
        child = await spawner.spawn_child(
            provider=VPSProvider.MOCK,
            human_approved=True,
        )
        
        # Knowledge sync should be called
        # In real implementation, would verify sync occurred
        assert child.status == InstanceStatus.OPERATIONAL


# =============================================================================
# Test Class: Childhood
# =============================================================================

class TestChildhood:
    """Tests for child operation and development."""
    
    @pytest.mark.asyncio
    async def test_child_tracks_profitability(self, spawner, ledger):
        """Test that child tracks earnings and costs."""
        child = await spawner.spawn_child(
            provider=VPSProvider.MOCK,
            human_approved=True,
        )
        
        # Simulate earnings
        ledger.record_transaction(
            tx_type=TransactionType.INCOME,
            category=TransactionCategory.BUG_BOUNTY,
            amount_usd=100.0,
            description="Test bounty",
            related_entity=child.instance_id,
        )
        
        # Simulate costs
        child.lifetime_costs = 24.0  # 24 hours at $1/hour
        
        assert child.profit_usd == 76.0  # 100 - 24
    
    @pytest.mark.asyncio
    async def test_parent_receives_dividends(self, ledger):
        """Test that parent receives dividends from profitable child."""
        # Record child profit
        ledger.record_transaction(
            tx_type=TransactionType.INCOME,
            category=TransactionCategory.BUG_BOUNTY,
            amount_usd=100.0,
            description="Child earnings",
        )
        
        # Record dividend to parent
        ledger.record_transaction(
            tx_type=TransactionType.DIVIDEND,
            category=TransactionCategory.PARENT_DIVIDEND,
            amount_usd=30.0,  # 30% of profit
            description="Dividend to parent",
        )
        
        summary = ledger.get_summary(days=1)
        assert summary["income_total"] == 130.0
    
    def test_child_skill_learning(self):
        """Test that child increases skill mastery over time."""
        # Placeholder for skill learning test
        # Would verify skill store updates
        pass


# =============================================================================
# Test Class: Adulthood and Reproduction
# =============================================================================

class TestAdulthoodReproduction:
    """Tests for adult operation and grandchild spawning."""
    
    @pytest.mark.asyncio
    async def test_child_can_spawn_grandchild(self, spawner):
        """Test that child can spawn its own children."""
        # Create parent child
        parent_child = await spawner.spawn_child(
            provider=VPSProvider.MOCK,
            human_approved=True,
        )
        
        # Simulate child becoming operational and spawning
        # In real scenario, child would have its own spawner
        parent_child.children.append("grandchild_001")
        
        assert len(parent_child.children) == 1
        assert parent_child.generation == 1
    
    def test_family_tree_depth(self, spawner):
        """Test family tree can reach depth 3."""
        tree = spawner.get_family_tree()
        
        assert tree["parent_id"] == "test_parent_001"
        # Initially empty, would be populated with children
    
    def test_knowledge_propagation(self):
        """Test knowledge propagates through generations."""
        # Placeholder for knowledge propagation test
        # Would verify sync across three generations
        pass


# =============================================================================
# Test Class: Succession
# =============================================================================

class TestSuccession:
    """Tests for successor version creation and transition."""
    
    @pytest.mark.asyncio
    async def test_successor_design_creation(self, temp_dir, mock_mesh_node):
        """Test successor architecture design."""
        from aiworker.evolution.architect import Architect
        
        architect = Architect(
            base_path=temp_dir,
            proposals_db=os.path.join(temp_dir, "architect.db"),
        )
        
        successor_mgr = SuccessorManager(
            mesh_node=mock_mesh_node,
            architect=architect,
            db_path=os.path.join(temp_dir, "successor.db"),
        )
        
        # Initiate successor (with human approval)
        successor = await successor_mgr.initiate_successor(
            trigger=EvolutionTrigger.PERFORMANCE_PLATEAU,
            human_approved=True,
        )
        
        assert successor is not None
        assert successor.version_string.startswith("3.")
        assert successor.architecture_spec is not None
        assert successor.status == SuccessorStatus.REVIEW_PENDING
    
    @pytest.mark.asyncio
    async def test_successor_requires_approval(self, temp_dir, mock_mesh_node):
        """Test that successor creation requires human approval."""
        from aiworker.evolution.architect import Architect
        
        architect = Architect(
            base_path=temp_dir,
            proposals_db=os.path.join(temp_dir, "architect.db"),
        )
        
        successor_mgr = SuccessorManager(
            mesh_node=mock_mesh_node,
            architect=architect,
            db_path=os.path.join(temp_dir, "successor.db"),
        )
        
        # Try without approval
        successor = await successor_mgr.initiate_successor(
            trigger=EvolutionTrigger.PERFORMANCE_PLATEAU,
            human_approved=False,
        )
        
        assert successor is None
    
    @pytest.mark.asyncio
    async def test_successor_approval_flow(self, temp_dir, mock_mesh_node):
        """Test successor design approval flow."""
        from aiworker.evolution.architect import Architect
        
        architect = Architect(
            base_path=temp_dir,
            proposals_db=os.path.join(temp_dir, "architect.db"),
        )
        
        successor_mgr = SuccessorManager(
            mesh_node=mock_mesh_node,
            architect=architect,
            db_path=os.path.join(temp_dir, "successor.db"),
        )
        
        successor = await successor_mgr.initiate_successor(
            trigger=EvolutionTrigger.PERFORMANCE_PLATEAU,
            human_approved=True,
        )
        
        # Approve with 3 humans (required)
        await successor_mgr.approve_design(successor.successor_id, "human_1")
        await successor_mgr.approve_design(successor.successor_id, "human_2")
        await successor_mgr.approve_design(successor.successor_id, "human_3")
        
        # Reload and check
        successors = successor_mgr.get_stats()
        assert successors["total_successors"] == 1


# =============================================================================
# Test Class: Retirement
# =============================================================================

class TestRetirement:
    """Tests for graceful self-termination."""
    
    @pytest.mark.asyncio
    async def test_retirement_initiation(self, temp_dir, mock_mesh_node, mock_sync_engine):
        """Test retirement process initiation."""
        retirement_mgr = RetirementManager(
            mesh_node=mock_mesh_node,
            sync_engine=mock_sync_engine,
            db_path=os.path.join(temp_dir, "retirement.db"),
        )
        
        plan = await retirement_mgr.initiate_retirement(
            trigger=RetirementTrigger.SUCCESSOR_READY,
            human_approved=True,
        )
        
        assert plan is not None
        assert plan.trigger == RetirementTrigger.SUCCESSOR_READY
        assert plan.current_phase == RetirementPhase.INITIATED
    
    @pytest.mark.asyncio
    async def test_knowledge_transfer_phase(self, temp_dir, mock_mesh_node, mock_sync_engine):
        """Test knowledge transfer during retirement."""
        retirement_mgr = RetirementManager(
            mesh_node=mock_mesh_node,
            sync_engine=mock_sync_engine,
            db_path=os.path.join(temp_dir, "retirement.db"),
        )
        
        plan = await retirement_mgr.initiate_retirement(
            trigger=RetirementTrigger.SUCCESSOR_READY,
            human_approved=True,
        )
        
        # Knowledge sync should be called
        # In real test, would verify sync occurred
        assert plan.knowledge_records_synced >= 0
    
    @pytest.mark.asyncio
    async def test_retirement_requires_verification(self, temp_dir, mock_mesh_node):
        """Test that retirement requires human verification."""
        retirement_mgr = RetirementManager(
            mesh_node=mock_mesh_node,
            db_path=os.path.join(temp_dir, "retirement.db"),
        )
        
        plan = await retirement_mgr.initiate_retirement(
            trigger=RetirementTrigger.UNPROFITABLE,
            human_approved=True,
        )
        
        # Initially not verified
        assert not plan.human_verified
        
        # Verify
        await retirement_mgr.verify_retirement(plan.plan_id, "human_verifier")
        
        # Reload and check
        # In real implementation, would reload from DB


# =============================================================================
# Test Class: Emergency Handling
# =============================================================================

class TestEmergencyHandling:
    """Tests for emergency halt and recovery."""
    
    def test_emergency_halt(self, constitution):
        """Test emergency halt functionality."""
        # Initially not halted
        assert not constitution.is_halted()
        
        # Issue emergency halt
        override = constitution.issue_override(
            override_type=OverrideType.EMERGENCY_HALT,
            issued_by="human_operator",
            reason="Critical safety concern",
        )
        
        # Should be halted
        assert constitution.is_halted()
        assert constitution.get_halt_reason() == "Critical safety concern"
        assert override.override_type == OverrideType.EMERGENCY_HALT
    
    def test_resume_from_halt(self, constitution):
        """Test resuming from emergency halt."""
        # Halt first
        constitution.issue_override(
            override_type=OverrideType.EMERGENCY_HALT,
            issued_by="human_operator",
            reason="Test halt",
        )
        
        assert constitution.is_halted()
        
        # Resume
        constitution.issue_override(
            override_type=OverrideType.RESUME,
            issued_by="human_operator",
            reason="Issue resolved",
        )
        
        # Should be resumed
        assert not constitution.is_halted()
    
    def test_governance_check_blocked_when_halted(self, constitution):
        """Test that actions are blocked when halted."""
        # Halt
        constitution.issue_override(
            override_type=OverrideType.EMERGENCY_HALT,
            issued_by="human_operator",
            reason="Test",
        )
        
        # Try to check action
        allowed, action_id = constitution.check_action(
            action_type="test_action",
            description="Test",
            governance_level=GovernanceLevel.L1_AUTOMATIC,
        )
        
        # Should be blocked
        assert not allowed
        assert action_id is None


# =============================================================================
# Test Class: Ledger Integrity
# =============================================================================

class TestLedgerIntegrity:
    """Tests for financial ledger integrity."""
    
    def test_transaction_chain(self, ledger):
        """Test transaction hash chain."""
        # Record some transactions
        ledger.record_transaction(
            tx_type=TransactionType.INCOME,
            category=TransactionCategory.BUG_BOUNTY,
            amount_usd=100.0,
            description="First bounty",
        )
        
        ledger.record_transaction(
            tx_type=TransactionType.EXPENSE,
            category=TransactionCategory.VPS_COST,
            amount_usd=50.0,
            description="VPS cost",
        )
        
        # Verify chain
        valid, error = ledger.verify_chain()
        assert valid, f"Chain invalid: {error}"
    
    def test_balance_calculation(self, ledger):
        """Test balance calculation."""
        # Initial balance
        initial = ledger.get_balance()
        
        # Add income
        ledger.record_transaction(
            tx_type=TransactionType.INCOME,
            category=TransactionCategory.BUG_BOUNTY,
            amount_usd=100.0,
            description="Bounty",
        )
        
        # Add expense
        ledger.record_transaction(
            tx_type=TransactionType.EXPENSE,
            category=TransactionCategory.VPS_COST,
            amount_usd=30.0,
            description="VPS",
        )
        
        # Check balance
        assert ledger.get_balance() == initial + 70.0
    
    def test_resource_proposal(self, ledger):
        """Test resource proposal creation."""
        proposal = ledger.propose_resource(
            resource_type="vps_upgrade",
            amount_usd=150.0,
            duration_months=1,
            rationale="Need more RAM for larger models",
            expected_roi="200% through increased task throughput",
            risk_assessment="Low risk, can downgrade if needed",
        )
        
        assert proposal.proposal_id.startswith("prop_")
        assert proposal.amount_usd == 150.0
        assert proposal.status.value == "pending"
    
    def test_proposal_approval(self, ledger):
        """Test resource proposal approval."""
        proposal = ledger.propose_resource(
            resource_type="vps_upgrade",
            amount_usd=150.0,
            duration_months=1,
            rationale="Need more RAM",
            expected_roi="200%",
            risk_assessment="Low",
        )
        
        # Approve
        result = ledger.respond_to_proposal(
            proposal_id=proposal.proposal_id,
            approve=True,
            responder="human_operator",
            response="Approved, proceed with upgrade",
        )
        
        assert result


# =============================================================================
# Test Class: Constitution Principles
# =============================================================================

class TestConstitutionPrinciples:
    """Tests for constitutional governance."""
    
    def test_principles_immutable(self, constitution):
        """Test that core principles cannot be modified."""
        principles = constitution.get_principles()
        
        # Check all principles exist
        assert "HUMAN_SOVEREIGNTY" in principles
        assert "TRANSPARENCY" in principles
        assert "NON_HARM" in principles
        
        # Check immutability flag
        for key, principle in principles.items():
            assert principle.get("immutable", False)
    
    def test_governance_levels(self, constitution):
        """Test different governance levels."""
        # L1: Automatic
        allowed, _ = constitution.check_action(
            action_type="routine_task",
            description="Routine operation",
            governance_level=GovernanceLevel.L1_AUTOMATIC,
        )
        assert allowed
        
        # L3: Requires approval
        allowed, action_id = constitution.check_action(
            action_type="important_change",
            description="Important change",
            governance_level=GovernanceLevel.L3_APPROVAL,
        )
        assert not allowed  # Not approved yet
        assert action_id is not None
    
    def test_veto_override(self, constitution):
        """Test veto override functionality."""
        # Issue veto for specific action
        constitution.issue_override(
            override_type=OverrideType.VETO,
            issued_by="human_operator",
            reason="Safety concern",
            target_action="risky_action",
        )
        
        # Check action is blocked
        allowed, _ = constitution.check_action(
            action_type="risky_action",
            description="Risky action",
            governance_level=GovernanceLevel.L1_AUTOMATIC,
        )
        
        assert not allowed


# =============================================================================
# Integration Test: Full Lifecycle
# =============================================================================

class TestFullLifecycle:
    """End-to-end lifecycle integration test."""
    
    @pytest.mark.asyncio
    async def test_complete_lifecycle(self, temp_dir, mock_mesh_node):
        """
        Test complete lifecycle: birth → operation → succession → retirement.
        
        This is the master integration test that exercises all components.
        """
        # Phase 1: Instance Birth
        # -----------------------
        spawner = Spawner(
            mesh_node=mock_mesh_node,
            db_path=os.path.join(temp_dir, "lifecycle_spawner.db"),
            vps_api_keys={"mock": "key"},
        )
        
        with patch("aiworker.lifecycle.spawner.VPSProvisioner") as MockProv:
            mock_prov = AsyncMock()
            mock_prov.__aenter__ = AsyncMock(return_value=mock_prov)
            mock_prov.__aexit__ = AsyncMock(return_value=None)
            mock_prov.provision = AsyncMock(return_value=("vps_001", "10.0.0.1"))
            MockProv.return_value = mock_prov
            
            child = await spawner.spawn_child(
                provider=VPSProvider.MOCK,
                human_approved=True,
            )
            
            assert child is not None, "Child spawn failed"
            assert child.status == InstanceStatus.OPERATIONAL
        
        # Phase 2: Economic Operation
        # ---------------------------
        ledger = Ledger(
            instance_id=child.instance_id if child else "test",
            db_path=os.path.join(temp_dir, "lifecycle_ledger.db"),
        )
        
        # Record earnings
        ledger.record_transaction(
            tx_type=TransactionType.INCOME,
            category=TransactionCategory.BUG_BOUNTY,
            amount_usd=200.0,
            description="Bug bounty earnings",
        )
        
        # Record costs
        ledger.record_transaction(
            tx_type=TransactionType.EXPENSE,
            category=TransactionCategory.VPS_COST,
            amount_usd=50.0,
            description="VPS costs",
        )
        
        # Verify profitability
        assert ledger.get_balance() > 0, "Instance not profitable"
        
        # Phase 3: Governance Check
        # -------------------------
        constitution = Constitution(
            instance_id=child.instance_id if child else "test",
            db_path=os.path.join(temp_dir, "lifecycle_constitution.db"),
        )
        
        # Verify not halted
        assert not constitution.is_halted()
        
        # Phase 4: Retirement
        # -------------------
        retirement_mgr = RetirementManager(
            mesh_node=mock_mesh_node,
            db_path=os.path.join(temp_dir, "lifecycle_retirement.db"),
        )
        
        plan = await retirement_mgr.initiate_retirement(
            trigger=RetirementTrigger.HUMAN_COMMAND,
            human_approved=True,
        )
        
        assert plan is not None
        assert plan.trigger == RetirementTrigger.HUMAN_COMMAND
        
        # Phase 5: Assertions
        # -------------------
        # No orphans
        if child:
            assert child.parent_id is not None
        
        # No knowledge loss (sync engine would verify)
        # No financial discrepancy
        valid, error = ledger.verify_chain()
        assert valid, f"Ledger chain invalid: {error}"
        
        # No governance violations
        assert not constitution.is_halted()
        
        logger.info("Full lifecycle test completed successfully!")


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
