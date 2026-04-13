#!/usr/bin/env python3
"""
AIWorker Sovereignty View - Human Control Interface
Phase 6: Autonomous Evolution & Self-Replication

FastAPI-based web interface providing human final authority over AIWorker.
Includes constitution viewing, override controls, family tree, ledger, and architecture.
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Any
from datetime import datetime

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Import AIWorker components
from aiworker.governance.constitution import (
    Constitution, OverrideType, GovernanceLevel, CONSTITUTIONAL_PRINCIPLES
)
from aiworker.economics.ledger import Ledger, TransactionType, TransactionCategory
from aiworker.lifecycle.spawner import Spawner
from aiworker.lifecycle.successor import SuccessorManager, EvolutionTrigger
from aiworker.lifecycle.retirement import RetirementManager, RetirementTrigger
from aiworker.evolution.architect import Architect

logger = logging.getLogger("aiworker.dashboard.sovereignty")

# =============================================================================
# Pydantic Models
# =============================================================================

class OverrideRequest(BaseModel):
    """Request to issue an override."""
    override_type: str
    reason: str
    target_action: Optional[str] = None
    target_instance: Optional[str] = None


class ProposalResponse(BaseModel):
    """Response to a resource proposal."""
    approve: bool
    response: Optional[str] = None
    counter_amount: Optional[float] = None


class SpawnRequest(BaseModel):
    """Request to spawn a child instance."""
    role: Optional[str] = None
    provider: str = "hetzner"
    region: str = "nbg1"


class RetirementRequest(BaseModel):
    """Request to initiate retirement."""
    trigger: str
    hibernate: bool = False


class SuccessorRequest(BaseModel):
    """Request to initiate successor creation."""
    trigger: str


# =============================================================================
# Sovereignty Dashboard
# =============================================================================

class SovereigntyDashboard:
    """
    Human control interface for AIWorker.
    
    Provides:
    - Constitution viewing and amendment interface
    - Emergency override controls
    - Family tree visualization
    - Ledger transparency
    - Architecture health monitoring
    """
    
    def __init__(
        self,
        constitution: Constitution,
        ledger: Ledger,
        spawner: Optional[Spawner] = None,
        successor_manager: Optional[SuccessorManager] = None,
        retirement_manager: Optional[RetirementManager] = None,
        architect: Optional[Architect] = None,
        host: str = "0.0.0.0",
        port: int = 8081,
    ):
        self.constitution = constitution
        self.ledger = ledger
        self.spawner = spawner
        self.successor_manager = successor_manager
        self.retirement_manager = retirement_manager
        self.architect = architect
        self.host = host
        self.port = port
        
        # FastAPI app
        self.app = FastAPI(
            title="AIWorker Sovereignty",
            description="Human control interface for AIWorker autonomous systems",
            version="2.0.0-phase6",
        )
        
        # WebSocket connections
        self.ws_clients: List[WebSocket] = []
        
        self._setup_routes()
        
        logger.info(f"SovereigntyDashboard initialized on {host}:{port}")
    
    def _setup_routes(self):
        """Setup API routes."""
        # Static files
        # self.app.mount("/static", StaticFiles(directory="static"), name="static")
        
        # Main page
        self.app.get("/", response_class=HTMLResponse)(self._handle_index)
        
        # Governance API
        self.app.get("/api/governance/constitution")(self._get_constitution)
        self.app.get("/api/governance/overrides")(self._get_overrides)
        self.app.post("/api/governance/override")(self._post_override)
        self.app.get("/api/governance/status")(self._get_governance_status)
        
        # Lifecycle API
        self.app.get("/api/lifecycle/family")(self._get_family_tree)
        self.app.post("/api/lifecycle/spawn")(self._post_spawn)
        self.app.post("/api/lifecycle/successor")(self._post_successor)
        self.app.post("/api/lifecycle/retire")(self._post_retire)
        
        # Economics API
        self.app.get("/api/economics/ledger")(self._get_ledger)
        self.app.get("/api/economics/summary")(self._get_economics_summary)
        self.app.post("/api/economics/proposal/{proposal_id}/respond")(self._respond_proposal)
        
        # Architecture API
        self.app.get("/api/architecture/health")(self._get_architecture_health)
        self.app.get("/api/architecture/proposals")(self._get_architecture_proposals)
        
        # WebSocket
        self.app.websocket("/ws")(self._websocket_handler)
    
    # =====================================================================
    # HTML Handler
    # =====================================================================
    
    async def _handle_index(self) -> HTMLResponse:
        """Serve main dashboard page."""
        html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AIWorker Sovereignty</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0a0a0f;
            color: #e0e0e0;
            min-height: 100vh;
        }
        
        .header {
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            padding: 20px;
            border-bottom: 1px solid #2a2a3e;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .header h1 {
            font-size: 24px;
            color: #ff4444;
            text-shadow: 0 0 10px rgba(255, 68, 68, 0.5);
        }
        
        .header .subtitle {
            color: #888;
            font-size: 14px;
        }
        
        .emergency-bar {
            background: #ff4444;
            color: white;
            padding: 10px;
            text-align: center;
            display: none;
        }
        
        .emergency-bar.active {
            display: block;
        }
        
        .container {
            display: grid;
            grid-template-columns: 250px 1fr;
            min-height: calc(100vh - 80px);
        }
        
        .sidebar {
            background: #151520;
            border-right: 1px solid #2a2a3e;
            padding: 20px;
        }
        
        .nav-item {
            padding: 12px 16px;
            margin-bottom: 8px;
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.2s;
            color: #888;
        }
        
        .nav-item:hover {
            background: #2a2a3e;
            color: #fff;
        }
        
        .nav-item.active {
            background: #00d4ff;
            color: #000;
        }
        
        .main-content {
            padding: 20px;
            overflow-y: auto;
        }
        
        .panel {
            background: #151520;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
            border: 1px solid #2a2a3e;
        }
        
        .panel h2 {
            font-size: 18px;
            color: #00d4ff;
            margin-bottom: 15px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .big-button {
            padding: 20px 40px;
            font-size: 18px;
            font-weight: bold;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.2s;
        }
        
        .big-button.red {
            background: #ff4444;
            color: white;
        }
        
        .big-button.red:hover {
            background: #ff6666;
            box-shadow: 0 0 20px rgba(255, 68, 68, 0.5);
        }
        
        .big-button.green {
            background: #00ff88;
            color: #000;
        }
        
        .metric {
            display: flex;
            justify-content: space-between;
            padding: 12px 0;
            border-bottom: 1px solid #2a2a3e;
        }
        
        .metric:last-child { border-bottom: none; }
        
        .metric-label { color: #888; }
        .metric-value { color: #fff; font-weight: 500; }
        
        .status-online { color: #00ff88; }
        .status-offline { color: #ff4444; }
        .status-warning { color: #ffaa00; }
        
        .principle-card {
            background: #1a1a2a;
            border-radius: 8px;
            padding: 15px;
            margin-bottom: 10px;
            border-left: 3px solid #00d4ff;
        }
        
        .principle-card h3 {
            color: #00d4ff;
            font-size: 14px;
            margin-bottom: 5px;
        }
        
        .principle-card p {
            color: #aaa;
            font-size: 13px;
        }
        
        .family-tree {
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 20px;
        }
        
        .tree-node {
            background: #1a1a2a;
            border-radius: 8px;
            padding: 15px 25px;
            margin: 10px;
            border: 2px solid #00d4ff;
            text-align: center;
        }
        
        .tree-node.self {
            border-color: #ff4444;
            background: #2a1a1a;
        }
        
        .tree-children {
            display: flex;
            gap: 20px;
            margin-top: 20px;
        }
        
        .ledger-table {
            width: 100%;
            border-collapse: collapse;
        }
        
        .ledger-table th,
        .ledger-table td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #2a2a3e;
        }
        
        .ledger-table th {
            color: #888;
            font-weight: normal;
        }
        
        .income { color: #00ff88; }
        .expense { color: #ff4444; }
        
        .health-score {
            font-size: 48px;
            font-weight: bold;
            text-align: center;
            padding: 20px;
        }
        
        .health-score.good { color: #00ff88; }
        .health-score.warning { color: #ffaa00; }
        .health-score.critical { color: #ff4444; }
        
        .proposal-card {
            background: #1a1a2a;
            border-radius: 8px;
            padding: 15px;
            margin-bottom: 10px;
        }
        
        .proposal-card h4 {
            color: #fff;
            margin-bottom: 10px;
        }
        
        .proposal-actions {
            display: flex;
            gap: 10px;
            margin-top: 10px;
        }
        
        .btn {
            padding: 8px 16px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 14px;
        }
        
        .btn-approve { background: #00ff88; color: #000; }
        .btn-reject { background: #ff4444; color: #fff; }
        .btn-info { background: #00d4ff; color: #000; }
        
        #connection-status {
            position: fixed;
            bottom: 20px;
            right: 20px;
            padding: 10px 20px;
            border-radius: 20px;
            background: #1a1a2e;
            border: 1px solid #2a2a3e;
        }
        
        #connection-status.connected {
            border-color: #00ff88;
            color: #00ff88;
        }
        
        #connection-status.disconnected {
            border-color: #ff4444;
            color: #ff4444;
        }
    </style>
</head>
<body>
    <div class="header">
        <div>
            <h1>⚠️ AIWorker Sovereignty</h1>
            <div class="subtitle">Human Control Interface - Final Authority</div>
        </div>
        <div id="system-status">Status: Operational</div>
    </div>
    
    <div class="emergency-bar" id="emergency-bar">
        🚨 SYSTEM HALTED - Emergency Override Active
    </div>
    
    <div class="container">
        <div class="sidebar">
            <div class="nav-item active" data-panel="overview">📊 Overview</div>
            <div class="nav-item" data-panel="constitution">📜 Constitution</div>
            <div class="nav-item" data-panel="overrides">🚨 Overrides</div>
            <div class="nav-item" data-panel="family">👨‍👩‍👧‍👦 Family Tree</div>
            <div class="nav-item" data-panel="ledger">💰 Ledger</div>
            <div class="nav-item" data-panel="architecture">🏗️ Architecture</div>
        </div>
        
        <div class="main-content">
            <!-- Overview Panel -->
            <div id="panel-overview" class="panel-content">
                <div class="panel">
                    <h2>⚡ Emergency Controls</h2>
                    <div style="display: flex; gap: 20px; margin-top: 20px;">
                        <button class="big-button red" onclick="emergencyHalt()">
                            🛑 EMERGENCY HALT
                        </button>
                        <button class="big-button green" onclick="resumeSystem()">
                            ▶️ RESUME SYSTEM
                        </button>
                    </div>
                </div>
                
                <div class="panel">
                    <h2>📈 System Status</h2>
                    <div id="system-metrics">
                        <div class="metric">
                            <span class="metric-label">Governance Status</span>
                            <span class="metric-value status-online" id="gov-status">Active</span>
                        </div>
                        <div class="metric">
                            <span class="metric-label">Active Overrides</span>
                            <span class="metric-value" id="active-overrides">0</span>
                        </div>
                        <div class="metric">
                            <span class="metric-label">Balance</span>
                            <span class="metric-value" id="balance">$0.00</span>
                        </div>
                        <div class="metric">
                            <span class="metric-label">Children</span>
                            <span class="metric-value" id="children-count">0</span>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- Constitution Panel -->
            <div id="panel-constitution" class="panel-content" style="display:none;">
                <div class="panel">
                    <h2>📜 Constitutional Principles</h2>
                    <div id="principles-list">
                        <!-- Populated by JS -->
                    </div>
                </div>
            </div>
            
            <!-- Overrides Panel -->
            <div id="panel-overrides" class="panel-content" style="display:none;">
                <div class="panel">
                    <h2>🚨 Active Overrides</h2>
                    <div id="overrides-list">
                        <p style="color: #888;">No active overrides</p>
                    </div>
                </div>
            </div>
            
            <!-- Family Tree Panel -->
            <div id="panel-family" class="panel-content" style="display:none;">
                <div class="panel">
                    <h2>👨‍👩‍👧‍👦 Family Tree</h2>
                    <div class="family-tree" id="family-tree">
                        <!-- Populated by JS -->
                    </div>
                </div>
                <div class="panel">
                    <h2>➕ Spawn Child</h2>
                    <div class="proposal-actions">
                        <button class="btn btn-approve" onclick="spawnChild()">Spawn New Child</button>
                    </div>
                </div>
            </div>
            
            <!-- Ledger Panel -->
            <div id="panel-ledger" class="panel-content" style="display:none;">
                <div class="panel">
                    <h2>💰 Financial Ledger</h2>
                    <div id="ledger-summary">
                        <div class="metric">
                            <span class="metric-label">Current Balance</span>
                            <span class="metric-value" id="ledger-balance">$0.00</span>
                        </div>
                        <div class="metric">
                            <span class="metric-label">30-Day Income</span>
                            <span class="metric-value income" id="ledger-income">$0.00</span>
                        </div>
                        <div class="metric">
                            <span class="metric-label">30-Day Expenses</span>
                            <span class="metric-value expense" id="ledger-expenses">$0.00</span>
                        </div>
                    </div>
                </div>
                <div class="panel">
                    <h2>📋 Recent Transactions</h2>
                    <table class="ledger-table" id="ledger-table">
                        <thead>
                            <tr>
                                <th>Time</th>
                                <th>Type</th>
                                <th>Category</th>
                                <th>Amount</th>
                                <th>Description</th>
                            </tr>
                        </thead>
                        <tbody>
                            <!-- Populated by JS -->
                        </tbody>
                    </table>
                </div>
            </div>
            
            <!-- Architecture Panel -->
            <div id="panel-architecture" class="panel-content" style="display:none;">
                <div class="panel">
                    <h2>🏗️ Architecture Health</h2>
                    <div class="health-score good" id="health-score">85</div>
                </div>
                <div class="panel">
                    <h2>📋 Improvement Proposals</h2>
                    <div id="architecture-proposals">
                        <!-- Populated by JS -->
                    </div>
                </div>
            </div>
        </div>
    </div>
    
    <div id="connection-status" class="disconnected">Disconnected</div>
    
    <script>
        // WebSocket connection
        let ws = null;
        let currentPanel = 'overview';
        
        function connect() {
            ws = new WebSocket(`ws://${window.location.host}/ws`);
            
            ws.onopen = () => {
                document.getElementById('connection-status').className = 'connected';
                document.getElementById('connection-status').textContent = 'Connected';
            };
            
            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                updateDashboard(data);
            };
            
            ws.onclose = () => {
                document.getElementById('connection-status').className = 'disconnected';
                document.getElementById('connection-status').textContent = 'Disconnected';
                setTimeout(connect, 5000);
            };
        }
        
        function updateDashboard(data) {
            // Update system status
            if (data.governance) {
                document.getElementById('gov-status').textContent = 
                    data.governance.halted ? 'HALTED' : 'Active';
                document.getElementById('gov-status').className = 
                    data.governance.halted ? 'metric-value status-offline' : 'metric-value status-online';
                document.getElementById('active-overrides').textContent = 
                    data.governance.active_overrides;
                
                if (data.governance.halted) {
                    document.getElementById('emergency-bar').classList.add('active');
                } else {
                    document.getElementById('emergency-bar').classList.remove('active');
                }
            }
            
            // Update ledger
            if (data.ledger) {
                document.getElementById('balance').textContent = 
                    `$${data.ledger.balance_usd.toFixed(2)}`;
                document.getElementById('ledger-balance').textContent = 
                    `$${data.ledger.balance_usd.toFixed(2)}`;
            }
            
            // Update family
            if (data.family) {
                document.getElementById('children-count').textContent = 
                    data.family.children.length;
                renderFamilyTree(data.family);
            }
        }
        
        function renderFamilyTree(family) {
            const container = document.getElementById('family-tree');
            container.innerHTML = `
                <div class="tree-node self">
                    <div><strong>Self</strong></div>
                    <div style="font-size: 12px; color: #888;">${family.parent_id.substring(0, 16)}...</div>
                </div>
                <div class="tree-children">
                    ${family.children.map(c => `
                        <div class="tree-node">
                            <div><strong>${c.role}</strong></div>
                            <div style="font-size: 12px; color: #888;">${c.instance_id.substring(0, 16)}...</div>
                            <div style="font-size: 11px; color: ${c.profit_usd >= 0 ? '#00ff88' : '#ff4444'};">
                                $${c.profit_usd.toFixed(2)}
                            </div>
                        </div>
                    `).join('')}
                </div>
            `;
        }
        
        // Navigation
        document.querySelectorAll('.nav-item').forEach(item => {
            item.addEventListener('click', () => {
                document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
                item.classList.add('active');
                
                const panel = item.dataset.panel;
                document.querySelectorAll('.panel-content').forEach(p => p.style.display = 'none');
                document.getElementById(`panel-${panel}`).style.display = 'block';
                
                currentPanel = panel;
                loadPanelData(panel);
            });
        });
        
        function loadPanelData(panel) {
            switch(panel) {
                case 'constitution':
                    fetch('/api/governance/constitution')
                        .then(r => r.json())
                        .then(data => renderConstitution(data));
                    break;
                case 'ledger':
                    fetch('/api/economics/summary')
                        .then(r => r.json())
                        .then(data => renderLedger(data));
                    break;
                case 'architecture':
                    fetch('/api/architecture/health')
                        .then(r => r.json())
                        .then(data => renderArchitecture(data));
                    break;
            }
        }
        
        function renderConstitution(data) {
            const container = document.getElementById('principles-list');
            container.innerHTML = Object.entries(data.principles).map(([key, p]) => `
                <div class="principle-card">
                    <h3>${key.replace(/_/g, ' ')}</h3>
                    <p>${p.text}</p>
                    <small style="color: #666;">Priority: ${p.priority}</small>
                </div>
            `).join('');
        }
        
        function renderLedger(data) {
            document.getElementById('ledger-income').textContent = 
                `$${data.income_total.toFixed(2)}`;
            document.getElementById('ledger-expenses').textContent = 
                `$${data.expense_total.toFixed(2)}`;
        }
        
        function renderArchitecture(data) {
            const score = document.getElementById('health-score');
            score.textContent = Math.round(data.health_score);
            score.className = 'health-score ' + 
                (data.health_score >= 80 ? 'good' : 
                 data.health_score >= 50 ? 'warning' : 'critical');
        }
        
        // Actions
        async function emergencyHalt() {
            if (!confirm('Are you sure you want to EMERGENCY HALT all AIWorker operations?')) return;
            
            await fetch('/api/governance/override', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    override_type: 'emergency_halt',
                    reason: 'Human-initiated emergency halt'
                })
            });
        }
        
        async function resumeSystem() {
            await fetch('/api/governance/override', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    override_type: 'resume',
                    reason: 'Human-initiated resume'
                })
            });
        }
        
        async function spawnChild() {
            await fetch('/api/lifecycle/spawn', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({provider: 'mock', region: 'test'})
            });
            alert('Child spawn initiated');
        }
        
        // Initialize
        connect();
        loadPanelData('overview');
    </script>
</body>
</html>"""
        
        return HTMLResponse(content=html)
    
    # =====================================================================
    # API Handlers
    # =====================================================================
    
    async def _get_constitution(self) -> Dict[str, Any]:
        """Get full constitution text."""
        return {
            "principles": self.constitution.get_principles(),
            "governance_levels": [l.name for l in GovernanceLevel],
        }
    
    async def _get_overrides(self) -> Dict[str, Any]:
        """Get active overrides."""
        return {
            "overrides": [
                ov.to_dict() for ov in self.constitution.active_overrides.values()
            ],
        }
    
    async def _post_override(self, request: OverrideRequest) -> Dict[str, Any]:
        """Issue an override."""
        try:
            override_type = OverrideType(request.override_type)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid override type")
        
        override = self.constitution.issue_override(
            override_type=override_type,
            issued_by="human_operator",  # Would be authenticated
            reason=request.reason,
            target_action=request.target_action,
            target_instance=request.target_instance,
        )
        
        await self._broadcast_update()
        
        return {"status": "success", "override_id": override.override_id}
    
    async def _get_governance_status(self) -> Dict[str, Any]:
        """Get current governance status."""
        return self.constitution.get_governance_status()
    
    async def _get_family_tree(self) -> Dict[str, Any]:
        """Get family tree visualization data."""
        if self.spawner:
            return self.spawner.get_family_tree()
        return {"parent_id": "unknown", "children": []}
    
    async def _post_spawn(self, request: SpawnRequest) -> Dict[str, Any]:
        """Spawn a child instance."""
        if not self.spawner:
            raise HTTPException(status_code=503, detail="Spawner not available")
        
        # This would be async in real implementation
        # child = await self.spawner.spawn_child(...)
        
        return {"status": "initiated", "message": "Child spawn initiated"}
    
    async def _post_successor(self, request: SuccessorRequest) -> Dict[str, Any]:
        """Initiate successor creation."""
        if not self.successor_manager:
            raise HTTPException(status_code=503, detail="Successor manager not available")
        
        try:
            trigger = EvolutionTrigger(request.trigger)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid trigger")
        
        # successor = await self.successor_manager.initiate_successor(trigger, human_approved=True)
        
        return {"status": "initiated", "message": "Successor creation initiated"}
    
    async def _post_retire(self, request: RetirementRequest) -> Dict[str, Any]:
        """Initiate retirement."""
        if not self.retirement_manager:
            raise HTTPException(status_code=503, detail="Retirement manager not available")
        
        try:
            trigger = RetirementTrigger(request.trigger)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid trigger")
        
        # plan = await self.retirement_manager.initiate_retirement(trigger, hibernate=request.hibernate)
        
        return {"status": "initiated", "message": "Retirement initiated"}
    
    async def _get_ledger(self, limit: int = 100) -> Dict[str, Any]:
        """Get ledger transactions."""
        transactions = self.ledger.get_transactions(limit=limit)
        return {
            "transactions": [tx.to_dict() for tx in transactions],
            "balance": self.ledger.get_balance(),
        }
    
    async def _get_economics_summary(self, days: int = 30) -> Dict[str, Any]:
        """Get economics summary."""
        return self.ledger.get_summary(days=days)
    
    async def _respond_proposal(
        self,
        proposal_id: str,
        response: ProposalResponse,
    ) -> Dict[str, Any]:
        """Respond to a resource proposal."""
        counter = None
        if response.counter_amount:
            counter = {"amount_usd": response.counter_amount}
        
        result = self.ledger.respond_to_proposal(
            proposal_id=proposal_id,
            approve=response.approve,
            responder="human_operator",
            response=response.response,
            counter=counter,
        )
        
        return {"status": "success" if result else "failed"}
    
    async def _get_architecture_health(self) -> Dict[str, Any]:
        """Get architecture health score."""
        if self.architect:
            return self.architect.get_stats()
        return {"health_score": 100, "modules_analyzed": 0}
    
    async def _get_architecture_proposals(self) -> Dict[str, Any]:
        """Get architecture improvement proposals."""
        if self.architect:
            proposals = self.architect.get_proposals(status="proposed")
            return {"proposals": [p.to_dict() for p in proposals]}
        return {"proposals": []}
    
    # =====================================================================
    # WebSocket Handler
    # =====================================================================
    
    async def _websocket_handler(self, websocket: WebSocket):
        """Handle WebSocket connections for real-time updates."""
        await websocket.accept()
        self.ws_clients.append(websocket)
        
        try:
            # Send initial state
            await self._send_state(websocket)
            
            # Keep connection alive
            while True:
                await asyncio.sleep(5)
                await self._send_state(websocket)
                
        except WebSocketDisconnect:
            self.ws_clients.remove(websocket)
    
    async def _send_state(self, websocket: WebSocket):
        """Send current state to WebSocket client."""
        state = {
            "governance": self.constitution.get_governance_status(),
            "ledger": self.ledger.get_stats(),
            "family": self.spawner.get_family_tree() if self.spawner else {},
            "timestamp": time.time(),
        }
        
        await websocket.send_json(state)
    
    async def _broadcast_update(self):
        """Broadcast update to all connected clients."""
        disconnected = []
        
        for ws in self.ws_clients:
            try:
                await self._send_state(ws)
            except Exception:
                disconnected.append(ws)
        
        for ws in disconnected:
            self.ws_clients.remove(ws)
    
    # =====================================================================
    # Server
    # =====================================================================
    
    async def start(self):
        """Start the dashboard server."""
        import uvicorn
        
        config = uvicorn.Config(
            self.app,
            host=self.host,
            port=self.port,
            log_level="info",
        )
        
        server = uvicorn.Server(config)
        await server.serve()


# =============================================================================
# Convenience Function
# =============================================================================

async def create_sovereignty_dashboard(
    constitution: Constitution,
    ledger: Ledger,
    spawner: Optional[Spawner] = None,
    successor_manager: Optional[SuccessorManager] = None,
    retirement_manager: Optional[RetirementManager] = None,
    architect: Optional[Architect] = None,
    host: str = "0.0.0.0",
    port: int = 8081,
) -> SovereigntyDashboard:
    """Create and start sovereignty dashboard."""
    dashboard = SovereigntyDashboard(
        constitution=constitution,
        ledger=ledger,
        spawner=spawner,
        successor_manager=successor_manager,
        retirement_manager=retirement_manager,
        architect=architect,
        host=host,
        port=port,
    )
    
    return dashboard
