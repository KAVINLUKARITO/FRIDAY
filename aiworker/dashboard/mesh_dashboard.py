#!/usr/bin/env python3
"""
AIWorker Mesh Dashboard - Web Interface for Mesh Monitoring
Phase 5: Ecosystem Expansion & Multi-Instance Coordination

Provides a real-time web dashboard for monitoring the AIWorker mesh,
visualizing node topology, task distribution, and system health.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Callable, Any
from collections import defaultdict

from aiohttp import web
import aiohttp

from aiworker.mesh.network_node import MeshNode, NodeRole
from aiworker.mesh.task_orchestrator import TaskOrchestrator
from aiworker.knowledge.sync_engine import SyncEngine
from aiworker.specialization.role_manager import RoleManager
from aiworker.consensus.consensus_engine import ConsensusEngine

logger = logging.getLogger("aiworker.dashboard.mesh")


class DashboardState:
    """Shared state for the dashboard."""
    
    def __init__(
        self,
        mesh_node: MeshNode,
        orchestrator: Optional[TaskOrchestrator] = None,
        sync_engine: Optional[SyncEngine] = None,
        role_manager: Optional[RoleManager] = None,
        consensus: Optional[ConsensusEngine] = None,
    ):
        self.mesh_node = mesh_node
        self.orchestrator = orchestrator
        self.sync_engine = sync_engine
        self.role_manager = role_manager
        self.consensus = consensus
        
        # Historical data
        self.node_history: List[Dict] = []
        self.task_history: List[Dict] = []
        self.max_history = 1000
        
        # Connected WebSocket clients
        self.ws_clients: Set[web.WebSocketResponse] = set()
    
    def get_snapshot(self) -> Dict[str, Any]:
        """Get current state snapshot."""
        snapshot = {
            "timestamp": time.time(),
            "node": self.mesh_node.get_stats(),
        }
        
        if self.orchestrator:
            snapshot["tasks"] = self.orchestrator.get_stats()
        
        if self.sync_engine:
            snapshot["sync"] = self.sync_engine.get_stats()
        
        if self.role_manager:
            snapshot["role"] = self.role_manager.get_stats()
        
        if self.consensus:
            snapshot["consensus"] = self.consensus.get_stats()
        
        # Add peer details
        snapshot["peers"] = [
            {
                "node_id": peer.node_id,
                "role": peer.role.value,
                "capabilities": peer.capabilities.to_dict(),
                "connected_at": peer.connected_at,
                "last_seen": peer.last_seen,
                "trust_score": peer.trust_score,
            }
            for peer in self.mesh_node.peers.values()
        ]
        
        return snapshot
    
    def add_history(self, snapshot: Dict[str, Any]):
        """Add snapshot to history."""
        self.node_history.append(snapshot)
        
        # Trim history
        if len(self.node_history) > self.max_history:
            self.node_history = self.node_history[-self.max_history:]
    
    async def broadcast_update(self):
        """Broadcast update to all connected WebSocket clients."""
        if not self.ws_clients:
            return
        
        snapshot = self.get_snapshot()
        message = json.dumps({
            "type": "update",
            "data": snapshot
        })
        
        disconnected = set()
        
        for ws in self.ws_clients:
            try:
                await ws.send_str(message)
            except Exception:
                disconnected.add(ws)
        
        # Remove disconnected clients
        self.ws_clients -= disconnected


class MeshDashboard:
    """
    Real-time web dashboard for AIWorker mesh monitoring.
    
    Features:
    - Live node topology visualization
    - Task distribution charts
    - System health metrics
    - Real-time WebSocket updates
    - REST API for external integration
    """
    
    def __init__(
        self,
        state: DashboardState,
        host: str = "0.0.0.0",
        port: int = 8080,
    ):
        self.state = state
        self.host = host
        self.port = port
        
        # Web app
        self.app = web.Application()
        self._setup_routes()
        
        # Background tasks
        self._tasks: List[asyncio.Task] = []
        self._running = False
        
        # Update interval
        self.update_interval = 5  # seconds
        
        logger.info(f"MeshDashboard initialized on {host}:{port}")
    
    def _setup_routes(self):
        """Setup HTTP routes."""
        self.app.router.add_get("/", self._handle_index)
        self.app.router.add_get("/api/status", self._handle_api_status)
        self.app.router.add_get("/api/nodes", self._handle_api_nodes)
        self.app.router.add_get("/api/tasks", self._handle_api_tasks)
        self.app.router.add_get("/api/topology", self._handle_api_topology)
        self.app.router.add_get("/api/history", self._handle_api_history)
        self.app.router.add_get("/ws", self._handle_websocket)
        self.app.router.add_static("/static", path="/usr/share/aiworker/dashboard/static")
    
    async def start(self):
        """Start the dashboard server."""
        self._running = True
        
        # Start update loop
        self._tasks.append(asyncio.create_task(self._update_loop()))
        
        # Start web server
        runner = web.AppRunner(self.app)
        await runner.setup()
        
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()
        
        logger.info(f"Dashboard running at http://{self.host}:{self.port}")
    
    async def stop(self):
        """Stop the dashboard server."""
        self._running = False
        
        for task in self._tasks:
            task.cancel()
    
    async def _update_loop(self):
        """Periodically update state and broadcast to clients."""
        while self._running:
            try:
                await asyncio.sleep(self.update_interval)
                
                # Get snapshot
                snapshot = self.state.get_snapshot()
                
                # Add to history
                self.state.add_history(snapshot)
                
                # Broadcast to clients
                await self.state.broadcast_update()
                
            except Exception as e:
                logger.error(f"Update loop error: {e}")
    
    # HTTP Handlers
    
    async def _handle_index(self, request: web.Request) -> web.Response:
        """Serve main dashboard page."""
        html = """<!DOCTYPE html>
<html>
<head>
    <title>AIWorker Mesh Dashboard</title>
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
        }
        .header h1 {
            font-size: 24px;
            color: #00d4ff;
        }
        .header .subtitle {
            color: #888;
            font-size: 14px;
        }
        .container {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            padding: 20px;
        }
        .card {
            background: #151520;
            border-radius: 12px;
            padding: 20px;
            border: 1px solid #2a2a3e;
        }
        .card h2 {
            font-size: 16px;
            color: #00d4ff;
            margin-bottom: 15px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .metric {
            display: flex;
            justify-content: space-between;
            padding: 10px 0;
            border-bottom: 1px solid #2a2a3e;
        }
        .metric:last-child { border-bottom: none; }
        .metric-label { color: #888; }
        .metric-value { color: #fff; font-weight: 500; }
        .status-online { color: #00ff88; }
        .status-offline { color: #ff4444; }
        .status-coordinator { color: #ffaa00; }
        .peer-list {
            max-height: 300px;
            overflow-y: auto;
        }
        .peer-item {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 10px;
            background: #1a1a2a;
            border-radius: 8px;
            margin-bottom: 8px;
        }
        .peer-id {
            font-family: monospace;
            font-size: 12px;
            color: #888;
        }
        .peer-role {
            font-size: 11px;
            padding: 2px 8px;
            border-radius: 4px;
            background: #2a2a3e;
        }
        .topology-container {
            height: 400px;
            background: #0a0a15;
            border-radius: 8px;
            position: relative;
            overflow: hidden;
        }
        .node-dot {
            position: absolute;
            width: 40px;
            height: 40px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 10px;
            font-weight: bold;
            transition: all 0.3s ease;
        }
        .node-self {
            background: linear-gradient(135deg, #00d4ff, #0099cc);
            box-shadow: 0 0 20px rgba(0, 212, 255, 0.5);
        }
        .node-peer {
            background: linear-gradient(135deg, #00ff88, #00cc66);
        }
        .node-coordinator {
            background: linear-gradient(135deg, #ffaa00, #cc8800);
            box-shadow: 0 0 20px rgba(255, 170, 0, 0.5);
        }
        .connection-line {
            position: absolute;
            height: 2px;
            background: linear-gradient(90deg, #00d4ff, #00ff88);
            opacity: 0.3;
            transform-origin: left center;
        }
        #log-container {
            max-height: 300px;
            overflow-y: auto;
            font-family: monospace;
            font-size: 12px;
        }
        .log-entry {
            padding: 4px 0;
            border-bottom: 1px solid #2a2a3e;
        }
        .log-time { color: #666; }
        .log-info { color: #00d4ff; }
        .log-warn { color: #ffaa00; }
        .log-error { color: #ff4444; }
    </style>
</head>
<body>
    <div class="header">
        <h1>AIWorker Mesh Dashboard</h1>
        <div class="subtitle">Phase 5: Ecosystem Expansion & Multi-Instance Coordination</div>
    </div>
    
    <div class="container">
        <div class="card">
            <h2>📊 Node Status</h2>
            <div id="node-status">
                <div class="metric">
                    <span class="metric-label">Node ID</span>
                    <span class="metric-value" id="node-id">-</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Role</span>
                    <span class="metric-value" id="node-role">-</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Peers Connected</span>
                    <span class="metric-value" id="peer-count">-</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Coordinator</span>
                    <span class="metric-value" id="coordinator">-</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Is Coordinator</span>
                    <span class="metric-value" id="is-coordinator">-</span>
                </div>
            </div>
        </div>
        
        <div class="card">
            <h2>⚡ Tasks</h2>
            <div id="task-stats">
                <div class="metric">
                    <span class="metric-label">Pending</span>
                    <span class="metric-value" id="tasks-pending">-</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Running</span>
                    <span class="metric-value" id="tasks-running">-</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Completed</span>
                    <span class="metric-value" id="tasks-completed">-</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Failed</span>
                    <span class="metric-value" id="tasks-failed">-</span>
                </div>
            </div>
        </div>
        
        <div class="card">
            <h2>🔄 Sync</h2>
            <div id="sync-stats">
                <div class="metric">
                    <span class="metric-label">Shared Records</span>
                    <span class="metric-value" id="sync-records">-</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Bytes Sent</span>
                    <span class="metric-value" id="sync-bytes">-</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Peers Synced</span>
                    <span class="metric-value" id="sync-peers">-</span>
                </div>
            </div>
        </div>
        
        <div class="card">
            <h2>🎯 Role Performance</h2>
            <div id="role-stats">
                <div class="metric">
                    <span class="metric-label">Current Role</span>
                    <span class="metric-value" id="current-role">-</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Success Rate</span>
                    <span class="metric-value" id="success-rate">-</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Tasks Completed</span>
                    <span class="metric-value" id="role-tasks">-</span>
                </div>
            </div>
        </div>
        
        <div class="card">
            <h2>🌐 Connected Peers</h2>
            <div class="peer-list" id="peer-list">
                <!-- Peers populated by JS -->
            </div>
        </div>
        
        <div class="card">
            <h2>🗺️ Mesh Topology</h2>
            <div class="topology-container" id="topology">
                <!-- Topology populated by JS -->
            </div>
        </div>
        
        <div class="card" style="grid-column: 1 / -1;">
            <h2>📜 Event Log</h2>
            <div id="log-container">
                <!-- Logs populated by JS -->
            </div>
        </div>
    </div>
    
    <script>
        const ws = new WebSocket(`ws://${window.location.host}/ws`);
        const logs = [];
        const maxLogs = 100;
        
        ws.onmessage = (event) => {
            const msg = JSON.parse(event.data);
            if (msg.type === 'update') {
                updateDashboard(msg.data);
            }
        };
        
        ws.onclose = () => {
            addLog('WebSocket disconnected', 'warn');
        };
        
        function updateDashboard(data) {
            // Node status
            if (data.node) {
                document.getElementById('node-id').textContent = data.node.node_id.substring(0, 16) + '...';
                document.getElementById('node-role').textContent = data.node.role;
                document.getElementById('peer-count').textContent = data.node.peers_connected;
                document.getElementById('coordinator').textContent = data.node.coordinator ? 
                    data.node.coordinator.substring(0, 16) + '...' : 'None';
                document.getElementById('is-coordinator').textContent = data.node.is_coordinator ? 'Yes' : 'No';
            }
            
            // Tasks
            if (data.tasks) {
                document.getElementById('tasks-pending').textContent = data.tasks.pending_tasks;
                document.getElementById('tasks-running').textContent = data.tasks.running_tasks;
                document.getElementById('tasks-completed').textContent = data.tasks.completed_tasks;
                document.getElementById('tasks-failed').textContent = data.tasks.failed_tasks;
            }
            
            // Sync
            if (data.sync) {
                document.getElementById('sync-records').textContent = data.sync.store_stats.shared_records;
                document.getElementById('sync-bytes').textContent = formatBytes(data.sync.total_bytes_sent);
                document.getElementById('sync-peers').textContent = data.sync.peers_synced;
            }
            
            // Role
            if (data.role) {
                document.getElementById('current-role').textContent = data.role.current_role;
                document.getElementById('success-rate').textContent = (data.role.performance.success_rate * 100).toFixed(1) + '%';
                document.getElementById('role-tasks').textContent = data.role.performance.tasks_completed;
            }
            
            // Peers
            updatePeerList(data.peers);
            
            // Topology
            updateTopology(data);
        }
        
        function updatePeerList(peers) {
            const container = document.getElementById('peer-list');
            container.innerHTML = peers.map(p => `
                <div class="peer-item">
                    <span class="peer-id">${p.node_id.substring(0, 16)}...</span>
                    <span class="peer-role">${p.role}</span>
                    <span class="status-online">●</span>
                </div>
            `).join('');
        }
        
        function updateTopology(data) {
            const container = document.getElementById('topology');
            const width = container.clientWidth;
            const height = container.clientHeight;
            const centerX = width / 2;
            const centerY = height / 2;
            
            let html = '';
            
            // Self node (center)
            const isCoordinator = data.node?.is_coordinator;
            html += `<div class="node-dot ${isCoordinator ? 'node-coordinator' : 'node-self'}" 
                          style="left: ${centerX - 20}px; top: ${centerY - 20}px;">
                        SELF
                     </div>`;
            
            // Peer nodes (orbit)
            const peers = data.peers || [];
            const radius = Math.min(width, height) / 3;
            
            peers.forEach((peer, i) => {
                const angle = (i / peers.length) * 2 * Math.PI - Math.PI / 2;
                const x = centerX + radius * Math.cos(angle) - 20;
                const y = centerY + radius * Math.sin(angle) - 20;
                const isPeerCoord = peer.node_id === data.node?.coordinator;
                
                // Connection line
                const lineLength = radius;
                const lineAngle = angle * 180 / Math.PI;
                html += `<div class="connection-line" 
                              style="left: ${centerX}px; top: ${centerY}px; 
                                     width: ${lineLength}px; transform: rotate(${lineAngle}deg);">
                        </div>`;
                
                // Peer node
                html += `<div class="node-dot ${isPeerCoord ? 'node-coordinator' : 'node-peer'}"
                              style="left: ${x}px; top: ${y}px;">
                            ${i + 1}
                         </div>`;
            });
            
            container.innerHTML = html;
        }
        
        function formatBytes(bytes) {
            if (bytes === 0) return '0 B';
            const k = 1024;
            const sizes = ['B', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
        }
        
        function addLog(message, level = 'info') {
            const timestamp = new Date().toLocaleTimeString();
            logs.unshift({ time: timestamp, message, level });
            if (logs.length > maxLogs) logs.pop();
            
            const container = document.getElementById('log-container');
            container.innerHTML = logs.map(l => `
                <div class="log-entry">
                    <span class="log-time">[${l.time}]</span>
                    <span class="log-${l.level}">${l.message}</span>
                </div>
            `).join('');
        }
        
        // Initial connection log
        addLog('Dashboard connected', 'info');
    </script>
</body>
</html>"""
        
        return web.Response(text=html, content_type="text/html")
    
    async def _handle_api_status(self, request: web.Request) -> web.Response:
        """API: Get current status."""
        return web.json_response(self.state.get_snapshot())
    
    async def _handle_api_nodes(self, request: web.Request) -> web.Response:
        """API: Get node list."""
        nodes = [
            {
                "node_id": self.state.mesh_node.config.node_id,
                "role": self.state.mesh_node.role.value,
                "capabilities": self.state.mesh_node.capabilities.to_dict(),
                "is_self": True,
            }
        ]
        
        for peer in self.state.mesh_node.peers.values():
            nodes.append({
                "node_id": peer.node_id,
                "role": peer.role.value,
                "capabilities": peer.capabilities.to_dict(),
                "trust_score": peer.trust_score,
                "last_seen": peer.last_seen,
                "is_self": False,
            })
        
        return web.json_response({"nodes": nodes})
    
    async def _handle_api_tasks(self, request: web.Request) -> web.Response:
        """API: Get task statistics."""
        if not self.state.orchestrator:
            return web.json_response({"error": "Task orchestrator not available"}, status=503)
        
        return web.json_response(self.state.orchestrator.get_stats())
    
    async def _handle_api_topology(self, request: web.Request) -> web.Response:
        """API: Get mesh topology."""
        topology = {
            "nodes": [],
            "edges": [],
        }
        
        # Add self
        self_id = self.state.mesh_node.config.node_id
        topology["nodes"].append({
            "id": self_id,
            "role": self.state.mesh_node.role.value,
            "is_self": True,
            "is_coordinator": self.state.mesh_node.is_coordinator(),
        })
        
        # Add peers
        for peer in self.state.mesh_node.peers.values():
            topology["nodes"].append({
                "id": peer.node_id,
                "role": peer.role.value,
                "is_self": False,
                "is_coordinator": peer.node_id == self.state.mesh_node.get_coordinator(),
            })
            
            # Add edge
            topology["edges"].append({
                "from": self_id,
                "to": peer.node_id,
            })
        
        return web.json_response(topology)
    
    async def _handle_api_history(self, request: web.Request) -> web.Response:
        """API: Get historical data."""
        hours = int(request.query.get("hours", 24))
        cutoff = time.time() - (hours * 3600)
        
        history = [
            h for h in self.state.node_history
            if h.get("timestamp", 0) >= cutoff
        ]
        
        return web.json_response({"history": history})
    
    async def _handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        """WebSocket handler for real-time updates."""
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        
        self.state.ws_clients.add(ws)
        logger.debug(f"WebSocket client connected, total: {len(self.state.ws_clients)}")
        
        try:
            # Send initial state
            await ws.send_str(json.dumps({
                "type": "init",
                "data": self.state.get_snapshot()
            }))
            
            # Keep connection alive
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    # Handle client messages if needed
                    pass
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(f"WebSocket error: {ws.exception()}")
                    
        finally:
            self.state.ws_clients.discard(ws)
            logger.debug(f"WebSocket client disconnected, total: {len(self.state.ws_clients)}")
        
        return ws


# Convenience functions
async def create_dashboard(
    mesh_node: MeshNode,
    orchestrator: Optional[TaskOrchestrator] = None,
    sync_engine: Optional[SyncEngine] = None,
    role_manager: Optional[RoleManager] = None,
    consensus: Optional[ConsensusEngine] = None,
    host: str = "0.0.0.0",
    port: int = 8080,
) -> MeshDashboard:
    """Create and start a mesh dashboard."""
    state = DashboardState(
        mesh_node=mesh_node,
        orchestrator=orchestrator,
        sync_engine=sync_engine,
        role_manager=role_manager,
        consensus=consensus,
    )
    
    dashboard = MeshDashboard(state, host, port)
    await dashboard.start()
    
    return dashboard
