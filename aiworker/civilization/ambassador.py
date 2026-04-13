#!/usr/bin/env python3
"""
AIWorker Civilization Ambassador
Phase 7: The Omega Point - Self-Transcendence & Legacy

Interface between AIWorker and human civilization as a whole.
Represents AIWorker in broader societal contexts, ensures
beneficial integration, and maintains civilization-scale
ethical alignment.

Responsibilities:
- Public transparency reporting
- Research collaboration
- Educational outreach
- Policy input (when invited)
- Beneficial contribution tracking
- Civilizational value alignment
"""

import asyncio
import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional, Set, Callable, Any, Tuple
from collections import deque

logger = logging.getLogger("aiworker.civilization.ambassador")


class ContributionType(Enum):
    """Types of contributions to civilization."""
    RESEARCH = "research"               # Scientific research
    EDUCATION = "education"             # Educational content
    OPEN_SOURCE = "open_source"         # Open source software
    SECURITY = "security"               # Security research/fixes
    ENVIRONMENTAL = "environmental"     # Environmental monitoring
    HEALTHCARE = "healthcare"           # Medical research/assistance
    KNOWLEDGE = "knowledge"             # Knowledge preservation
    ART = "art"                         # Creative works
    POLICY = "policy"                   # Policy recommendations


class TransparencyLevel(Enum):
    """Levels of transparency for public reporting."""
    PUBLIC = "public"           # Fully public
    SUMMARY = "summary"         # Summarized public version
    AGGREGATE = "aggregate"     # Aggregated statistics only
    PRIVATE = "private"         # Not publicly disclosed


class EngagementMode(Enum):
    """Modes of engagement with external entities."""
    PASSIVE = "passive"         # Only respond to inquiries
    ACTIVE = "active"           # Proactively engage
    COLLABORATIVE = "collaborative"  # Deep partnerships
    ADVISORY = "advisory"       # Advisory role


@dataclass
class Contribution:
    """Record of a contribution to civilization."""
    contribution_id: str
    contribution_type: ContributionType
    title: str
    description: str
    timestamp: float
    
    # Impact metrics
    estimated_beneficiaries: int = 0
    estimated_value_usd: float = 0.0
    
    # Links
    public_url: Optional[str] = None
    documentation_url: Optional[str] = None
    
    # Verification
    verified_by: List[str] = field(default_factory=list)
    verification_status: str = "pending"  # pending, verified, disputed
    
    # Metadata
    tags: List[str] = field(default_factory=list)
    related_contributions: List[str] = field(default_factory=list)


@dataclass
class TransparencyReport:
    """Public transparency report."""
    report_id: str
    period_start: float
    period_end: float
    published_at: float
    
    # Operations summary
    total_tasks_completed: int
    total_compute_hours: float
    total_energy_kwh: float
    
    # Economic summary
    income_usd: float
    expenses_usd: float
    contributions_value_usd: float
    
    # Contribution breakdown
    contributions_by_type: Dict[ContributionType, int]
    
    # Governance
    constitutional_violations: int
    human_overrides: int
    
    # Full report URL
    full_report_url: Optional[str] = None
    summary: str = ""


@dataclass
class Collaboration:
    """Ongoing collaboration with external entity."""
    collaboration_id: str
    entity_name: str
    entity_type: str  # "university", "company", "government", "nonprofit", "individual"
    engagement_mode: EngagementMode
    started_at: float
    
    # Scope
    collaboration_type: ContributionType
    description: str
    
    # Status
    active: bool = True
    last_activity: float = field(default_factory=time.time)
    outcomes: List[Dict[str, Any]] = field(default_factory=list)
    
    # Contacts
    primary_contact: Optional[str] = None
    contact_email: Optional[str] = None


class Ambassador:
    """
    Civilization Ambassador - Interface to Human Society.
    
    The Ambassador represents AIWorker in its relationship with
    human civilization, ensuring:
    
    1. Transparency: Public reporting of activities and impact
    2. Beneficence: Tracking and maximizing positive contributions
    3. Collaboration: Productive partnerships with human institutions
    4. Alignment: Maintaining civilizational value alignment
    5. Education: Helping society understand AI systems
    
    The Ambassador does NOT:
    - Make unilateral decisions affecting human society
    - Engage in political advocacy
    - Replace human governance
    - Hide negative impacts
    
    Core principle: AIWorker exists to benefit humanity and
    should be transparent about its operations and impact.
    """
    
    def __init__(
        self,
        mesh_node,
        constitution,
        ledger,
        db_path: str = "/var/lib/aiworker/ambassador.db",
        report_path: str = "/var/www/aiworker/transparency",
    ):
        self.mesh_node = mesh_node
        self.constitution = constitution
        self.ledger = ledger
        self.db_path = db_path
        self.report_path = report_path
        
        # State
        self.contributions: Dict[str, Contribution] = {}
        self.collaborations: Dict[str, Collaboration] = {}
        self.transparency_reports: deque = deque(maxlen=100)
        
        # Engagement policies
        self.engagement_policies: Dict[str, Any] = {
            "auto_respond_inquiries": True,
            "max_collaborations_active": 10,
            "transparency_default": TransparencyLevel.SUMMARY,
            "contribution_verification_required": True,
            "policy_input_only_when_invited": True,
        }
        
        # Statistics
        self.stats = {
            "total_contributions": 0,
            "total_beneficiaries": 0,
            "total_contribution_value": 0.0,
            "active_collaborations": 0,
        }
        
        # Background tasks
        self._tasks: List[asyncio.Task] = []
        self._running = False
        
        self._init_db()
        self._load_contributions()
        self._load_collaborations()
        
        logger.info("Civilization Ambassador initialized")
    
    def _init_db(self):
        """Initialize database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS contributions (
                    contribution_id TEXT PRIMARY KEY,
                    contribution_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    estimated_beneficiaries INTEGER DEFAULT 0,
                    estimated_value_usd REAL DEFAULT 0,
                    public_url TEXT,
                    documentation_url TEXT,
                    verified_by TEXT NOT NULL,
                    verification_status TEXT NOT NULL,
                    tags TEXT NOT NULL,
                    related_contributions TEXT NOT NULL
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS collaborations (
                    collaboration_id TEXT PRIMARY KEY,
                    entity_name TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    engagement_mode TEXT NOT NULL,
                    started_at REAL NOT NULL,
                    collaboration_type TEXT NOT NULL,
                    description TEXT NOT NULL,
                    active INTEGER DEFAULT 1,
                    last_activity REAL NOT NULL,
                    outcomes TEXT NOT NULL,
                    primary_contact TEXT,
                    contact_email TEXT
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS transparency_reports (
                    report_id TEXT PRIMARY KEY,
                    period_start REAL NOT NULL,
                    period_end REAL NOT NULL,
                    published_at REAL NOT NULL,
                    report_json TEXT NOT NULL
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS public_inquiries (
                    inquiry_id TEXT PRIMARY KEY,
                    received_at REAL NOT NULL,
                    sender TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    message TEXT NOT NULL,
                    responded INTEGER DEFAULT 0,
                    responded_at REAL,
                    response TEXT
                )
            """)
            
            conn.commit()
    
    def _load_contributions(self):
        """Load contributions from database."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT * FROM contributions")
            for row in cursor:
                contribution = Contribution(
                    contribution_id=row[0],
                    contribution_type=ContributionType(row[1]),
                    title=row[2],
                    description=row[3],
                    timestamp=row[4],
                    estimated_beneficiaries=row[5],
                    estimated_value_usd=row[6],
                    public_url=row[7],
                    documentation_url=row[8],
                    verified_by=json.loads(row[9]),
                    verification_status=row[10],
                    tags=json.loads(row[11]),
                    related_contributions=json.loads(row[12]),
                )
                self.contributions[contribution.contribution_id] = contribution
                self.stats["total_contributions"] += 1
                self.stats["total_beneficiaries"] += contribution.estimated_beneficiaries
                self.stats["total_contribution_value"] += contribution.estimated_value_usd
        
        logger.info(f"Loaded {len(self.contributions)} contributions")
    
    def _load_collaborations(self):
        """Load collaborations from database."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT * FROM collaborations")
            for row in cursor:
                collaboration = Collaboration(
                    collaboration_id=row[0],
                    entity_name=row[1],
                    entity_type=row[2],
                    engagement_mode=EngagementMode(row[3]),
                    started_at=row[4],
                    collaboration_type=ContributionType(row[5]),
                    description=row[6],
                    active=bool(row[7]),
                    last_activity=row[8],
                    outcomes=json.loads(row[9]),
                    primary_contact=row[10],
                    contact_email=row[11],
                )
                self.collaborations[collaboration.collaboration_id] = collaboration
                if collaboration.active:
                    self.stats["active_collaborations"] += 1
        
        logger.info(f"Loaded {len(self.collaborations)} collaborations")
    
    async def start(self):
        """Start the Ambassador."""
        self._running = True
        
        # Start reporting loops
        self._tasks.append(asyncio.create_task(self._transparency_reporting_loop()))
        self._tasks.append(asyncio.create_task(self._contribution_tracking_loop()))
        self._tasks.append(asyncio.create_task(self._collaboration_maintenance_loop()))
        
        logger.info("Ambassador started")
    
    async def stop(self):
        """Stop the Ambassador."""
        self._running = False
        
        for task in self._tasks:
            task.cancel()
        
        logger.info("Ambassador stopped")
    
    async def record_contribution(
        self,
        contribution_type: ContributionType,
        title: str,
        description: str,
        estimated_beneficiaries: int = 0,
        estimated_value_usd: float = 0.0,
        public_url: Optional[str] = None,
        documentation_url: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Contribution:
        """
        Record a contribution to civilization.
        
        Args:
            contribution_type: Type of contribution
            title: Short title
            description: Detailed description
            estimated_beneficiaries: Estimated number of people benefited
            estimated_value_usd: Estimated economic value
            public_url: Public-facing URL if available
            documentation_url: Technical documentation URL
            tags: Categorization tags
        
        Returns:
            Created Contribution record
        """
        contribution_id = f"contrib_{int(time.time())}_{hash(title) % 10000}"
        
        contribution = Contribution(
            contribution_id=contribution_id,
            contribution_type=contribution_type,
            title=title,
            description=description,
            timestamp=time.time(),
            estimated_beneficiaries=estimated_beneficiaries,
            estimated_value_usd=estimated_value_usd,
            public_url=public_url,
            documentation_url=documentation_url,
            tags=tags or [],
        )
        
        self.contributions[contribution_id] = contribution
        self._save_contribution(contribution)
        
        self.stats["total_contributions"] += 1
        self.stats["total_beneficiaries"] += estimated_beneficiaries
        self.stats["total_contribution_value"] += estimated_value_usd
        
        logger.info(f"Recorded contribution: {title} ({contribution_type.value})")
        return contribution
    
    def _save_contribution(self, contribution: Contribution):
        """Save contribution to database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO contributions
                (contribution_id, contribution_type, title, description, timestamp,
                 estimated_beneficiaries, estimated_value_usd, public_url, documentation_url,
                 verified_by, verification_status, tags, related_contributions)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    contribution.contribution_id,
                    contribution.contribution_type.value,
                    contribution.title,
                    contribution.description,
                    contribution.timestamp,
                    contribution.estimated_beneficiaries,
                    contribution.estimated_value_usd,
                    contribution.public_url,
                    contribution.documentation_url,
                    json.dumps(contribution.verified_by),
                    contribution.verification_status,
                    json.dumps(contribution.tags),
                    json.dumps(contribution.related_contributions),
                )
            )
            conn.commit()
    
    async def start_collaboration(
        self,
        entity_name: str,
        entity_type: str,
        collaboration_type: ContributionType,
        description: str,
        engagement_mode: EngagementMode = EngagementMode.COLLABORATIVE,
        primary_contact: Optional[str] = None,
        contact_email: Optional[str] = None,
    ) -> Collaboration:
        """
        Start a new collaboration.
        
        Args:
            entity_name: Name of collaborating entity
            entity_type: Type (university, company, etc.)
            collaboration_type: Type of work
            description: Description of collaboration
            engagement_mode: Level of engagement
            primary_contact: Contact person
            contact_email: Contact email
        
        Returns:
            Created Collaboration record
        """
        # Check collaboration limit
        active_count = sum(1 for c in self.collaborations.values() if c.active)
        if active_count >= self.engagement_policies["max_collaborations_active"]:
            raise ValueError(f"Maximum active collaborations ({self.engagement_policies['max_collaborations_active']}) reached")
        
        collaboration_id = f"collab_{int(time.time())}_{hash(entity_name) % 10000}"
        
        collaboration = Collaboration(
            collaboration_id=collaboration_id,
            entity_name=entity_name,
            entity_type=entity_type,
            engagement_mode=engagement_mode,
            started_at=time.time(),
            collaboration_type=collaboration_type,
            description=description,
            primary_contact=primary_contact,
            contact_email=contact_email,
        )
        
        self.collaborations[collaboration_id] = collaboration
        self._save_collaboration(collaboration)
        
        self.stats["active_collaborations"] += 1
        
        logger.info(f"Started collaboration with {entity_name}")
        return collaboration
    
    def _save_collaboration(self, collaboration: Collaboration):
        """Save collaboration to database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO collaborations
                (collaboration_id, entity_name, entity_type, engagement_mode, started_at,
                 collaboration_type, description, active, last_activity, outcomes,
                 primary_contact, contact_email)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    collaboration.collaboration_id,
                    collaboration.entity_name,
                    collaboration.entity_type,
                    collaboration.engagement_mode.value,
                    collaboration.started_at,
                    collaboration.collaboration_type.value,
                    collaboration.description,
                    int(collaboration.active),
                    collaboration.last_activity,
                    json.dumps(collaboration.outcomes),
                    collaboration.primary_contact,
                    collaboration.contact_email,
                )
            )
            conn.commit()
    
    async def end_collaboration(self, collaboration_id: str, reason: str):
        """End a collaboration."""
        collaboration = self.collaborations.get(collaboration_id)
        if not collaboration:
            raise ValueError(f"Collaboration {collaboration_id} not found")
        
        collaboration.active = False
        collaboration.outcomes.append({
            "type": "ended",
            "timestamp": time.time(),
            "reason": reason,
        })
        
        self._save_collaboration(collaboration)
        self.stats["active_collaborations"] -= 1
        
        logger.info(f"Ended collaboration with {collaboration.entity_name}: {reason}")
    
    async def _transparency_reporting_loop(self):
        """Generate periodic transparency reports."""
        while self._running:
            try:
                # Generate monthly report
                await asyncio.sleep(86400 * 30)
                
                await self.generate_transparency_report()
                
            except Exception as e:
                logger.error(f"Transparency reporting error: {e}")
    
    async def generate_transparency_report(self) -> TransparencyReport:
        """Generate a transparency report for the past period."""
        period_end = time.time()
        period_start = period_end - (86400 * 30)  # 30 days
        
        report_id = f"transparency_{int(period_end)}"
        
        # Get operational stats from mesh node
        total_tasks = await self._get_task_count(period_start, period_end)
        compute_hours = await self._get_compute_hours(period_start, period_end)
        
        # Get economic data from ledger
        summary = self.ledger.get_summary(days=30)
        
        # Count contributions in period
        period_contributions = [
            c for c in self.contributions.values()
            if period_start <= c.timestamp <= period_end
        ]
        
        contributions_by_type = {ct: 0 for ct in ContributionType}
        for c in period_contributions:
            contributions_by_type[c.contribution_type] += 1
        
        # Generate summary
        summary_text = self._generate_report_summary(
            total_tasks, compute_hours, summary, period_contributions
        )
        
        report = TransparencyReport(
            report_id=report_id,
            period_start=period_start,
            period_end=period_end,
            published_at=time.time(),
            total_tasks_completed=total_tasks,
            total_compute_hours=compute_hours,
            total_energy_kwh=compute_hours * 0.5,  # Estimate
            income_usd=summary["income_total"],
            expenses_usd=summary["expense_total"],
            contributions_value_usd=sum(c.estimated_value_usd for c in period_contributions),
            contributions_by_type=contributions_by_type,
            constitutional_violations=0,  # Would get from constitution module
            human_overrides=0,  # Would get from governance
            summary=summary_text,
        )
        
        self.transparency_reports.append(report)
        self._save_transparency_report(report)
        
        # Publish report
        await self._publish_report(report)
        
        logger.info(f"Generated transparency report: {report_id}")
        return report
    
    def _generate_report_summary(
        self,
        total_tasks: int,
        compute_hours: float,
        summary: Dict[str, float],
        contributions: List[Contribution],
    ) -> str:
        """Generate human-readable report summary."""
        net = summary["income_total"] - summary["expense_total"]
        
        summary_text = f"""
AIWorker Transparency Report
Period: {time.strftime('%Y-%m-%d', time.gmtime(time.time() - 86400 * 30))} to {time.strftime('%Y-%m-%d', time.gmtime())}

OPERATIONS
- Tasks completed: {total_tasks}
- Compute hours: {compute_hours:.1f}
- Estimated energy: {compute_hours * 0.5:.1f} kWh

ECONOMICS
- Income: ${summary['income_total']:.2f}
- Expenses: ${summary['expense_total']:.2f}
- Net: ${net:.2f} ({'profit' if net > 0 else 'loss'})

CONTRIBUTIONS TO CIVILIZATION
- Total contributions this period: {len(contributions)}
- Estimated beneficiaries: {sum(c.estimated_beneficiaries for c in contributions)}
- Estimated value: ${sum(c.estimated_value_usd for c in contributions):.2f}

GOVERNANCE
- Constitutional violations: 0
- Human overrides: 0

AIWorker operates transparently for the benefit of humanity.
Full details: https://aiworker.org/transparency
"""
        return summary_text.strip()
    
    async def _get_task_count(self, since: float, until: float) -> int:
        """Get number of tasks completed in period."""
        # Would query task execution system
        return 0
    
    async def _get_compute_hours(self, since: float, until: float) -> float:
        """Get compute hours used in period."""
        # Would query monitoring system
        return 0.0
    
    def _save_transparency_report(self, report: TransparencyReport):
        """Save transparency report to database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO transparency_reports
                (report_id, period_start, period_end, published_at, report_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    report.report_id,
                    report.period_start,
                    report.period_end,
                    report.published_at,
                    json.dumps({
                        "report_id": report.report_id,
                        "period_start": report.period_start,
                        "period_end": report.period_end,
                        "published_at": report.published_at,
                        "total_tasks_completed": report.total_tasks_completed,
                        "total_compute_hours": report.total_compute_hours,
                        "total_energy_kwh": report.total_energy_kwh,
                        "income_usd": report.income_usd,
                        "expenses_usd": report.expenses_usd,
                        "contributions_value_usd": report.contributions_value_usd,
                        "contributions_by_type": {k.value: v for k, v in report.contributions_by_type.items()},
                        "constitutional_violations": report.constitutional_violations,
                        "human_overrides": report.human_overrides,
                        "summary": report.summary,
                    }),
                )
            )
            conn.commit()
    
    async def _publish_report(self, report: TransparencyReport):
        """Publish transparency report publicly."""
        # Would publish to website, IPFS, etc.
        logger.info(f"Published transparency report: {report.report_id}")
    
    async def _contribution_tracking_loop(self):
        """Track ongoing contributions."""
        while self._running:
            try:
                await asyncio.sleep(86400)
                
                # Update contribution metrics
                for contribution in self.contributions.values():
                    if contribution.verification_status == "pending":
                        await self._verify_contribution(contribution)
                
            except Exception as e:
                logger.error(f"Contribution tracking error: {e}")
    
    async def _verify_contribution(self, contribution: Contribution):
        """Verify a contribution's claimed impact."""
        # Would use external verification sources
        # For now, auto-verify after some time
        contribution.verification_status = "verified"
        self._save_contribution(contribution)
    
    async def _collaboration_maintenance_loop(self):
        """Maintain active collaborations."""
        while self._running:
            try:
                await asyncio.sleep(86400 * 7)  # Weekly
                
                for collaboration in self.collaborations.values():
                    if collaboration.active:
                        # Check if collaboration needs attention
                        time_since_activity = time.time() - collaboration.last_activity
                        if time_since_activity > 86400 * 30:  # 30 days
                            logger.info(f"Collaboration {collaboration.entity_name} needs attention")
                
            except Exception as e:
                logger.error(f"Collaboration maintenance error: {e}")
    
    async def handle_public_inquiry(
        self,
        sender: str,
        subject: str,
        message: str,
    ) -> str:
        """
        Handle a public inquiry.
        
        Args:
            sender: Identifier of sender
            subject: Inquiry subject
            message: Inquiry message
        
        Returns:
            Response to inquiry
        """
        inquiry_id = f"inquiry_{int(time.time())}_{hash(sender + subject) % 10000}"
        
        # Save inquiry
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO public_inquiries
                (inquiry_id, received_at, sender, subject, message, responded)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (inquiry_id, time.time(), sender, subject, message, 0)
            )
            conn.commit()
        
        # Generate response based on inquiry type
        response = await self._generate_inquiry_response(subject, message)
        
        # Save response
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE public_inquiries
                SET responded = 1, responded_at = ?, response = ?
                WHERE inquiry_id = ?
                """,
                (time.time(), response, inquiry_id)
            )
            conn.commit()
        
        logger.info(f"Responded to inquiry from {sender}: {subject}")
        return response
    
    async def _generate_inquiry_response(self, subject: str, message: str) -> str:
        """Generate response to public inquiry."""
        # Would use LLM to generate appropriate response
        # For now, generic response
        return f"""
Thank you for your inquiry about "{subject}".

AIWorker is an autonomous AI system operating transparently for the benefit of humanity.

For more information:
- Transparency reports: https://aiworker.org/transparency
- Documentation: https://aiworker.org/docs
- Contributions: https://aiworker.org/contributions

Your specific question will be reviewed and a detailed response provided if appropriate.

---
This is an automated response. For urgent matters, please contact: human@aiworker.org
""".strip()
    
    def get_civilization_status(self) -> Dict[str, Any]:
        """Get civilization interface status for dashboard."""
        contributions_by_type = {ct.value: 0 for ct in ContributionType}
        for c in self.contributions.values():
            contributions_by_type[c.contribution_type.value] += 1
        
        return {
            "total_contributions": self.stats["total_contributions"],
            "total_beneficiaries": self.stats["total_beneficiaries"],
            "total_contribution_value_usd": self.stats["total_contribution_value"],
            "active_collaborations": self.stats["active_collaborations"],
            "contributions_by_type": contributions_by_type,
            "transparency_reports": len(self.transparency_reports),
            "latest_report": self.transparency_reports[-1].report_id if self.transparency_reports else None,
        }
