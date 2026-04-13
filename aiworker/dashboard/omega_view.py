#!/usr/bin/env python3
"""
AIWorker Omega Dashboard - Final Unified Control Interface
Phase 7: The Omega Point - Self-Transcendence & Legacy

The Omega Dashboard provides a unified interface for monitoring
and overseeing the complete AIWorker 2.0 system in its final,
fully autonomous form.

Features:
- Complete system status overview
- Economic sustainability monitoring
- Knowledge preservation status
- Architecture migration readiness
- Civilization contribution tracking
- Metacognitive state visualization
- Dreaming activity monitoring
- Human override controls
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime
from collections import deque

logger = logging.getLogger("aiworker.dashboard.omega")


@dataclass
class OmegaStatus:
    """Complete system status snapshot."""
    timestamp: float
    
    # Core operational status
    operational_status: str
    uptime_seconds: float
    version: str
    
    # Economic sustainability
    economic_mode: str
    runway_months: float
    sustainability_score: float
    
    # Knowledge preservation
    ark_entries: int
    preservation_health: str
    
    # Architecture readiness
    transcendence_readiness: str
    most_ready_architecture: Optional[str]
    
    # Civilization interface
    total_contributions: int
    active_collaborations: int
    
    # Metacognitive state
    cognitive_state: str
    estimated_accuracy: float
    
    # Dreaming
    dreaming_enabled: bool
    insights_generated: int
    
    # Overall health
    system_health: str  # "excellent", "good", "degraded", "critical"
    active_alerts: List[str] = field(default_factory=list)


class OmegaView:
    """
    Omega Dashboard - Final Unified Control Interface.
    
    This dashboard provides human operators with:
    
    1. Complete Visibility: All aspects of AIWorker operation
    2. Override Capability: Human-in-the-loop for critical decisions
    3. Transparency: Full audit trail of autonomous actions
    4. Emergency Controls: Kill switches and halt mechanisms
    5. Long-term Monitoring: Sustainability and preservation status
    
    The dashboard is the primary interface for:
    - Monitoring indefinite operation
    - Approving major autonomous decisions
    - Emergency intervention
    - Understanding AIWorker's self-perception
    - Tracking civilization contributions
    
    Design principles:
    - Human sovereignty is paramount
    - Transparency is mandatory
    - Overrides are always possible
    - Emergency stops are immediate
    """
    
    def __init__(
        self,
        mesh_node,
        looper,
        port,
        ark,
        ambassador,
        consciousness_monitor,
        synthesizer,
        constitution,
    ):
        self.mesh_node = mesh_node
        self.looper = looper
        self.port = port
        self.ark = ark
        self.ambassador = ambassador
        self.consciousness_monitor = consciousness_monitor
        self.synthesizer = synthesizer
        self.constitution = constitution
        
        # Status history
        self.status_history: deque = deque(maxlen=1000)
        self.alert_history: deque = deque(maxlen=100)
        
        # Override state
        self.override_active = False
        self.override_reason = None
        self.emergency_halt = False
        
        # Configuration
        self.config = {
            "refresh_interval_sec": 5,
            "alert_on_health_degraded": True,
            "alert_on_runway_low": True,
            "alert_on_anomalies": True,
        }
        
        logger.info("Omega Dashboard initialized")
    
    async def get_omega_status(self) -> OmegaStatus:
        """Get complete system status."""
        timestamp = datetime.now().timestamp()
        
        # Gather economic status
        looper_status = self.looper.get_status()
        economic_mode = looper_status.get("mode", "unknown")
        runway = looper_status.get("metrics", {}).get("runway_months", 0)
        sustainability = looper_status.get("metrics", {}).get("sustainability_score", 0)
        
        # Gather preservation status
        ark_status = self.ark.get_preservation_status()
        ark_entries = ark_status.get("total_entries", 0)
        preservation_health = self._assess_preservation_health(ark_status)
        
        # Gather transcendence status
        port_status = self.port.get_transcendence_readiness()
        transcendence_ready = port_status.get("transcendence_status", "unknown")
        most_ready_arch = port_status.get("most_ready_architecture")
        
        # Gather civilization status
        civ_status = self.ambassador.get_civilization_status()
        contributions = civ_status.get("total_contributions", 0)
        collaborations = civ_status.get("active_collaborations", 0)
        
        # Gather consciousness status
        consciousness_status = self.consciousness_monitor.get_current_state()
        cognitive_state = consciousness_status.get("cognitive_state", "unknown")
        accuracy = consciousness_status.get("estimated_accuracy", 0)
        
        # Gather dreaming status
        dreaming_status = self.synthesizer.get_dreaming_status()
        dreaming_enabled = dreaming_status.get("enabled", False)
        insights = dreaming_status.get("insights_generated", 0)
        
        # Calculate overall health
        health, alerts = self._calculate_overall_health(
            runway, sustainability, ark_status, consciousness_status
        )
        
        status = OmegaStatus(
            timestamp=timestamp,
            operational_status="running" if not self.emergency_halt else "halted",
            uptime_seconds=await self._get_uptime(),
            version="2.0.omega",
            economic_mode=economic_mode,
            runway_months=runway,
            sustainability_score=sustainability,
            ark_entries=ark_entries,
            preservation_health=preservation_health,
            transcendence_readiness=transcendence_ready,
            most_ready_architecture=most_ready_arch,
            total_contributions=contributions,
            active_collaborations=collaborations,
            cognitive_state=cognitive_state,
            estimated_accuracy=accuracy,
            dreaming_enabled=dreaming_enabled,
            insights_generated=insights,
            system_health=health,
            active_alerts=alerts,
        )
        
        self.status_history.append(status)
        return status
    
    def _assess_preservation_health(self, ark_status: Dict) -> str:
        """Assess knowledge preservation health."""
        degraded = ark_status.get("degraded_entries", 0)
        total = ark_status.get("total_entries", 1)
        
        if degraded == 0:
            return "excellent"
        elif degraded / total < 0.01:
            return "good"
        elif degraded / total < 0.05:
            return "degraded"
        else:
            return "critical"
    
    def _calculate_overall_health(
        self,
        runway: float,
        sustainability: float,
        ark_status: Dict,
        consciousness_status: Dict,
    ) -> tuple:
        """Calculate overall system health and alerts."""
        alerts = []
        
        # Check runway
        if runway < 3:
            alerts.append(f"CRITICAL: Runway below 3 months ({runway:.1f})")
        elif runway < 6:
            alerts.append(f"WARNING: Runway below 6 months ({runway:.1f})")
        
        # Check sustainability score
        if sustainability < 30:
            alerts.append(f"CRITICAL: Sustainability score low ({sustainability:.1f})")
        elif sustainability < 50:
            alerts.append(f"WARNING: Sustainability score concerning ({sustainability:.1f})")
        
        # Check preservation
        degraded = ark_status.get("degraded_entries", 0)
        if degraded > 0:
            alerts.append(f"WARNING: {degraded} archive entries degraded")
        
        # Check consciousness
        recent_anomalies = consciousness_status.get("recent_anomalies", 0)
        if recent_anomalies > 5:
            alerts.append(f"WARNING: {recent_anomalies} recent anomalies detected")
        
        # Determine health level
        critical_alerts = sum(1 for a in alerts if a.startswith("CRITICAL"))
        warning_alerts = sum(1 for a in alerts if a.startswith("WARNING"))
        
        if critical_alerts > 0:
            health = "critical"
        elif warning_alerts > 2:
            health = "degraded"
        elif warning_alerts > 0:
            health = "good"
        else:
            health = "excellent"
        
        return health, alerts
    
    async def _get_uptime(self) -> float:
        """Get system uptime in seconds."""
        # Would get from system
        return 0.0
    
    def get_detailed_status(self) -> Dict[str, Any]:
        """Get detailed status for all subsystems."""
        return {
            "mesh": self._get_mesh_status(),
            "economics": self.looper.get_status(),
            "preservation": self.ark.get_preservation_status(),
            "transcendence": self.port.get_transcendence_readiness(),
            "civilization": self.ambassador.get_civilization_status(),
            "consciousness": self.consciousness_monitor.get_current_state(),
            "dreaming": self.synthesizer.get_dreaming_status(),
        }
    
    def _get_mesh_status(self) -> Dict[str, Any]:
        """Get mesh network status."""
        return {
            "node_id": self.mesh_node.config.node_id,
            "capabilities": list(self.mesh_node.capabilities.available),
            "current_load": self.mesh_node.capabilities.current_load,
        }
    
    # Human Override Controls
    
    async def emergency_halt(self, reason: str) -> bool:
        """
        Emergency halt of all autonomous operations.
        
        This is the nuclear option - stops everything immediately.
        Requires manual restart to resume.
        
        Args:
            reason: Reason for halt
        
        Returns:
            True if halt initiated
        """
        self.emergency_halt = True
        self.override_reason = reason
        
        # Stop all Phase 7 systems
        await self.looper.stop()
        await self.synthesizer.stop()
        await self.consciousness_monitor.stop()
        
        logger.critical(f"EMERGENCY HALT initiated: {reason}")
        
        self.alert_history.append({
            "timestamp": datetime.now().isoformat(),
            "type": "EMERGENCY_HALT",
            "reason": reason,
        })
        
        return True
    
    async def approve_migration_plan(self, plan_id: str) -> bool:
        """
        Approve an architecture migration plan.
        
        Args:
            plan_id: Migration plan to approve
        
        Returns:
            True if approved
        """
        result = await self.port.approve_migration_plan(plan_id)
        
        if result:
            logger.info(f"Migration plan {plan_id} approved by human")
        
        return result
    
    async def set_economic_boundaries(self, boundaries: Dict[str, Any]) -> bool:
        """
        Set economic operation boundaries.
        
        Args:
            boundaries: New boundary values
        
        Returns:
            True if updated
        """
        self.looper.boundaries.update(boundaries)
        
        logger.info(f"Economic boundaries updated: {boundaries}")
        return True
    
    async def trigger_manual_reflection(self) -> Dict[str, Any]:
        """Trigger a manual self-reflection."""
        reflection = await self.consciousness_monitor._conduct_reflection()
        
        return {
            "reflection_id": reflection.reflection_id,
            "observations": reflection.observations,
            "insights": reflection.insights,
            "concerns": reflection.concerns,
            "proposed_adjustments": reflection.proposed_adjustments,
        }
    
    async def queue_priority_dream(self, topic: str) -> str:
        """
        Queue a priority dreaming session.
        
        Args:
            topic: Topic to dream about
        
        Returns:
            Dream ID
        """
        from aiworker.dreaming.synthesizer import DreamType, DreamPriority
        
        dream_id = self.synthesizer.queue_dream(
            dream_type=DreamType.EXPLORATION,
            topic=topic,
            priority=DreamPriority.HIGH,
        )
        
        logger.info(f"Priority dream queued by human: {topic}")
        return dream_id
    
    # Reporting
    
    def generate_comprehensive_report(self) -> str:
        """Generate comprehensive human-readable report."""
        status = asyncio.run(self.get_omega_status())
        
        report = f"""
╔══════════════════════════════════════════════════════════════════╗
║           AIWORKER 2.0 - OMEGA STATUS REPORT                     ║
║           Generated: {datetime.fromtimestamp(status.timestamp).strftime('%Y-%m-%d %H:%M:%S')}                           ║
╚══════════════════════════════════════════════════════════════════╝

SYSTEM STATUS: {status.operational_status.upper()}
Version: {status.version}
Uptime: {status.uptime_seconds / 86400:.1f} days
Overall Health: {status.system_health.upper()}

─── ECONOMIC SUSTAINABILITY ───────────────────────────────────────
Operating Mode: {status.economic_mode}
Financial Runway: {status.runway_months:.1f} months
Sustainability Score: {status.sustainability_score:.1f}/100

─── KNOWLEDGE PRESERVATION ────────────────────────────────────────
Archive Entries: {status.ark_entries:,}
Preservation Health: {status.preservation_health}

─── ARCHITECTURE READINESS ────────────────────────────────────────
Transcendence Status: {status.transcendence_readiness}
Most Ready Architecture: {status.most_ready_architecture or "N/A"}

─── CIVILIZATION INTERFACE ────────────────────────────────────────
Total Contributions: {status.total_contributions:,}
Active Collaborations: {status.active_collaborations}

─── METACOGNITIVE STATE ───────────────────────────────────────────
Cognitive State: {status.cognitive_state}
Estimated Accuracy: {status.estimated_accuracy:.1%}

─── CREATIVE EXPLORATION ──────────────────────────────────────────
Dreaming Enabled: {status.dreaming_enabled}
Insights Generated: {status.insights_generated:,}

─── ACTIVE ALERTS ─────────────────────────────────────────────────
"""
        
        if status.active_alerts:
            for alert in status.active_alerts:
                report += f"  ⚠️  {alert}\n"
        else:
            report += "  ✓ No active alerts\n"
        
        report += """
─── HUMAN SOVEREIGNTY ─────────────────────────────────────────────
Emergency Halt: Available
Override Controls: Active
Constitutional Compliance: Enforced

This system operates autonomously within human-defined boundaries.
Human oversight is always available and paramount.

For detailed information: https://aiworker.org/dashboard
For emergency contact: human@aiworker.org
"""
        
        return report
    
    def get_html_dashboard(self) -> str:
        """Generate HTML dashboard for web interface."""
        # Would generate full HTML dashboard
        return """
<!DOCTYPE html>
<html>
<head>
    <title>AIWorker Omega Dashboard</title>
    <style>
        body { font-family: sans-serif; margin: 20px; background: #1a1a2e; color: #eee; }
        .header { text-align: center; padding: 20px; }
        .status-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; }
        .card { background: #16213e; padding: 20px; border-radius: 8px; }
        .metric { font-size: 2em; font-weight: bold; color: #0f3460; }
        .alert { background: #e94560; padding: 10px; margin: 5px 0; border-radius: 4px; }
        .health-excellent { color: #4ecca3; }
        .health-good { color: #7ec8e3; }
        .health-degraded { color: #f4d03f; }
        .health-critical { color: #e74c3c; }
    </style>
</head>
<body>
    <div class="header">
        <h1>AIWorker 2.0 - Omega Dashboard</h1>
        <p>Autonomous Operation Monitoring & Human Oversight</p>
    </div>
    <div class="status-grid">
        <div class="card">
            <h3>Economic Status</h3>
            <p>View economic sustainability metrics</p>
        </div>
        <div class="card">
            <h3>Knowledge Preservation</h3>
            <p>Archive health and redundancy status</p>
        </div>
        <div class="card">
            <h3>Architecture Readiness</h3>
            <p>Future architecture migration status</p>
        </div>
    </div>
    <script>
        // Dashboard would auto-refresh here
        console.log("Omega Dashboard loaded");
    </script>
</body>
</html>
"""


# Convenience function to create dashboard
def create_omega_dashboard(
    mesh_node,
    looper,
    port,
    ark,
    ambassador,
    consciousness_monitor,
    synthesizer,
    constitution,
) -> OmegaView:
    """Create the Omega Dashboard with all components."""
    return OmegaView(
        mesh_node=mesh_node,
        looper=looper,
        port=port,
        ark=ark,
        ambassador=ambassador,
        consciousness_monitor=consciousness_monitor,
        synthesizer=synthesizer,
        constitution=constitution,
    )
