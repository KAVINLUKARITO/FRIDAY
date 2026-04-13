#!/usr/bin/env python3
"""
AIWorker Architect - Meta-Level Architectural Improvement System
Phase 6: Autonomous Evolution & Self-Replication

Analyzes and improves AIWorker's own architecture beyond code patches.
Generates migration scripts, restructures modules, and maintains system health.
"""

import ast
import hashlib
import json
import logging
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any, Callable
import sqlite3

logger = logging.getLogger("aiworker.evolution.architect")


class ImprovementType(Enum):
    """Types of architectural improvements."""
    REFACTOR = "refactor"      # Restructure without behavior change
    MERGE = "merge"            # Combine redundant modules
    EXTRACT = "extract"        # Pull out common functionality
    REPLACE = "replace"        # Swap implementation
    ADD = "add"                # New architectural layer
    REMOVE = "remove"          # Remove deprecated components


class AnalysisMetric(Enum):
    """Metrics for architectural analysis."""
    COUPLING = "coupling"           # Module interdependence
    COHESION = "cohesion"           # Module internal unity
    COMPLEXITY = "complexity"       # Cyclomatic complexity
    REDUNDANCY = "redundancy"       # Duplicate functionality
    ABSTRACTION = "abstraction"     # Abstraction level appropriateness
    PERFORMANCE = "performance"     # Runtime performance
    MAINTAINABILITY = "maintainability"  # Ease of maintenance


@dataclass
class ModuleAnalysis:
    """Analysis results for a single module."""
    module_path: str
    lines_of_code: int
    num_classes: int
    num_functions: int
    imports: List[str]
    imported_by: List[str]
    complexity_score: float
    coupling_score: float
    cohesion_score: float
    issues: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ArchitecturalIssue:
    """Identified architectural issue."""
    issue_id: str
    metric: AnalysisMetric
    severity: str  # critical, high, medium, low
    description: str
    affected_modules: List[str]
    suggested_action: ImprovementType
    estimated_effort: str  # hours
    expected_benefit: str


@dataclass
class ImprovementProposal:
    """Proposal for architectural improvement."""
    proposal_id: str
    improvement_type: ImprovementType
    title: str
    description: str
    affected_files: List[str]
    migration_script: str
    rollback_script: str
    test_plan: str
    
    # Safety requirements
    required_approvals: int = 2
    integration_tests_required: bool = True
    performance_benchmark_required: bool = True
    
    # Status
    status: str = "proposed"  # proposed, approved, implementing, testing, deployed, rolled_back
    approvals: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "improvement_type": self.improvement_type.value,
            "title": self.title,
            "description": self.description,
            "affected_files": self.affected_files,
            "required_approvals": self.required_approvals,
            "status": self.status,
            "approvals": self.approvals,
        }


class CodeAnalyzer:
    """Analyzes Python code for architectural metrics."""
    
    def __init__(self, base_path: str = "/opt/aiworker"):
        self.base_path = Path(base_path)
        self.module_graph: Dict[str, ModuleAnalysis] = {}
    
    def analyze_module(self, module_path: str) -> ModuleAnalysis:
        """Analyze a single module."""
        full_path = self.base_path / module_path
        
        if not full_path.exists():
            raise FileNotFoundError(f"Module not found: {module_path}")
        
        with open(full_path, "r") as f:
            source = f.read()
        
        # Parse AST
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            logger.error(f"Syntax error in {module_path}: {e}")
            return ModuleAnalysis(
                module_path=module_path,
                lines_of_code=0,
                num_classes=0,
                num_functions=0,
                imports=[],
                imported_by=[],
                complexity_score=0.0,
                coupling_score=0.0,
                cohesion_score=0.0,
                issues=[{"type": "syntax_error", "message": str(e)}]
            )
        
        # Count components
        num_classes = len([n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)])
        num_functions = len([n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)])
        
        # Extract imports
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend([alias.name for alias in node.names])
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")
        
        # Calculate complexity (simplified)
        complexity = self._calculate_complexity(tree)
        
        analysis = ModuleAnalysis(
            module_path=module_path,
            lines_of_code=len(source.splitlines()),
            num_classes=num_classes,
            num_functions=num_functions,
            imports=imports,
            imported_by=[],  # Filled later
            complexity_score=complexity,
            coupling_score=0.0,  # Filled later
            cohesion_score=self._calculate_cohesion(tree),
            issues=[]
        )
        
        return analysis
    
    def _calculate_complexity(self, tree: ast.AST) -> float:
        """Calculate cyclomatic complexity approximation."""
        complexity = 1  # Base complexity
        
        for node in ast.walk(tree):
            if isinstance(node, (ast.If, ast.While, ast.For, ast.ExceptHandler)):
                complexity += 1
            elif isinstance(node, ast.BoolOp):
                complexity += len(node.values) - 1
        
        return complexity
    
    def _calculate_cohesion(self, tree: ast.AST) -> float:
        """Calculate module cohesion (simplified)."""
        # Higher is better (0-1 scale)
        # Measures how related the functions/classes are
        
        classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
        functions = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
        
        if not classes and not functions:
            return 1.0
        
        # Simple heuristic: fewer top-level functions = more cohesive
        if not classes:
            return max(0.0, 1.0 - (len(functions) * 0.1))
        
        return 0.8  # Default for class-based modules
    
    def build_dependency_graph(self) -> Dict[str, List[str]]:
        """Build module dependency graph."""
        # Find all Python files
        python_files = list(self.base_path.rglob("*.py"))
        
        # Analyze each module
        for py_file in python_files:
            rel_path = str(py_file.relative_to(self.base_path))
            try:
                analysis = self.analyze_module(rel_path)
                self.module_graph[rel_path] = analysis
            except Exception as e:
                logger.warning(f"Failed to analyze {rel_path}: {e}")
        
        # Build reverse dependencies
        for module_path, analysis in self.module_graph.items():
            for imported in analysis.imports:
                # Convert import to file path
                import_path = imported.replace(".", "/") + ".py"
                for other_path in self.module_graph:
                    if other_path.endswith(import_path):
                        self.module_graph[other_path].imported_by.append(module_path)
        
        # Calculate coupling
        for module_path, analysis in self.module_graph.items():
            # Coupling = (imports + imported_by) / total_modules
            total_deps = len(analysis.imports) + len(analysis.imported_by)
            analysis.coupling_score = min(1.0, total_deps / max(1, len(self.module_graph)))
        
        return {k: v.imports for k, v in self.module_graph.items()}
    
    def find_issues(self) -> List[ArchitecturalIssue]:
        """Find architectural issues in the codebase."""
        issues = []
        
        # Check for high coupling
        for module_path, analysis in self.module_graph.items():
            if analysis.coupling_score > 0.7:
                issues.append(ArchitecturalIssue(
                    issue_id=f"coupling_{hashlib.sha256(module_path.encode()).hexdigest()[:8]}",
                    metric=AnalysisMetric.COUPLING,
                    severity="high",
                    description=f"{module_path} has high coupling ({analysis.coupling_score:.2f})",
                    affected_modules=[module_path],
                    suggested_action=ImprovementType.REFACTOR,
                    estimated_effort="4-8 hours",
                    expected_benefit="Reduced maintenance cost, easier testing"
                ))
        
        # Check for large modules
        for module_path, analysis in self.module_graph.items():
            if analysis.lines_of_code > 1000:
                issues.append(ArchitecturalIssue(
                    issue_id=f"size_{hashlib.sha256(module_path.encode()).hexdigest()[:8]}",
                    metric=AnalysisMetric.MAINTAINABILITY,
                    severity="medium",
                    description=f"{module_path} is very large ({analysis.lines_of_code} lines)",
                    affected_modules=[module_path],
                    suggested_action=ImprovementType.EXTRACT,
                    estimated_effort="2-4 hours",
                    expected_benefit="Better code organization, parallel development"
                ))
        
        # Check for high complexity
        for module_path, analysis in self.module_graph.items():
            if analysis.complexity_score > 20:
                issues.append(ArchitecturalIssue(
                    issue_id=f"complexity_{hashlib.sha256(module_path.encode()).hexdigest()[:8]}",
                    metric=AnalysisMetric.COMPLEXITY,
                    severity="high",
                    description=f"{module_path} has high complexity (score: {analysis.complexity_score})",
                    affected_modules=[module_path],
                    suggested_action=ImprovementType.REFACTOR,
                    estimated_effort="3-6 hours",
                    expected_benefit="Easier understanding, fewer bugs"
                ))
        
        # Check for duplicate functionality
        function_signatures: Dict[str, List[str]] = {}
        for module_path, analysis in self.module_graph.items():
            full_path = self.base_path / module_path
            if full_path.exists():
                with open(full_path) as f:
                    source = f.read()
                try:
                    tree = ast.parse(source)
                    for node in ast.walk(tree):
                        if isinstance(node, ast.FunctionDef):
                            sig = f"{node.name}:{len(node.args.args)}"
                            function_signatures.setdefault(sig, []).append(module_path)
                except SyntaxError:
                    pass
        
        for sig, modules in function_signatures.items():
            if len(modules) > 2:
                issues.append(ArchitecturalIssue(
                    issue_id=f"redundancy_{hashlib.sha256(sig.encode()).hexdigest()[:8]}",
                    metric=AnalysisMetric.REDUNDANCY,
                    severity="medium",
                    description=f"Function pattern '{sig}' appears in {len(modules)} modules",
                    affected_modules=modules,
                    suggested_action=ImprovementType.EXTRACT,
                    estimated_effort="2-3 hours",
                    expected_benefit="Single source of truth, reduced code size"
                ))
        
        return issues


class MigrationGenerator:
    """Generates migration scripts for architectural changes."""
    
    def __init__(self, base_path: str = "/opt/aiworker"):
        self.base_path = Path(base_path)
    
    def generate_refactor_migration(
        self,
        source_module: str,
        target_modules: List[Tuple[str, List[str]]]  # [(new_path, [functions/classes])]
    ) -> Tuple[str, str]:
        """
        Generate migration script for module refactoring.
        
        Returns:
            (migration_script, rollback_script)
        """
        migration_steps = []
        rollback_steps = []
        
        # Step 1: Create new modules
        for new_path, components in target_modules:
            migration_steps.append(f"# Create {new_path}")
            migration_steps.append(f"mkdir -p $(dirname {new_path})")
            
            # Extract components
            migration_steps.append(f"# Extract {', '.join(components)} from {source_module}")
            
            rollback_steps.append(f"# Remove {new_path}")
            rollback_steps.append(f"rm -f {new_path}")
        
        # Step 2: Update imports
        migration_steps.append(f"# Update imports in dependent modules")
        migration_steps.append(f"find {self.base_path} -name '*.py' -exec sed -i 's/from {source_module.replace('/', '.').replace('.py', '')}/from NEW_MODULE/g' {{}} \\;")
        
        rollback_steps.append(f"# Restore imports")
        rollback_steps.append(f"git checkout -- '*.py'  # Restore from git")
        
        # Step 3: Create compatibility shim
        migration_steps.append(f"# Create compatibility shim at {source_module}")
        migration_steps.append(f"cat > {source_module} << 'EOF'")
        migration_steps.append(f"# Compatibility shim - redirects to new modules")
        migration_steps.append(f"import warnings")
        for new_path, components in target_modules:
            module_name = new_path.replace("/", ".").replace(".py", "")
            for comp in components:
                migration_steps.append(f"from {module_name} import {comp}")
        migration_steps.append(f"warnings.warn('{source_module} is deprecated', DeprecationWarning)")
        migration_steps.append("EOF")
        
        rollback_steps.append(f"# Remove compatibility shim")
        rollback_steps.append(f"git checkout -- {source_module}")
        
        migration = "\n".join(migration_steps)
        rollback = "\n".join(rollback_steps)
        
        return migration, rollback
    
    def generate_merge_migration(
        self,
        source_modules: List[str],
        target_module: str
    ) -> Tuple[str, str]:
        """Generate migration for merging modules."""
        migration_steps = []
        rollback_steps = []
        
        # Create merged module
        migration_steps.append(f"# Create merged module: {target_module}")
        migration_steps.append(f"mkdir -p $(dirname {target_module})")
        
        for src in source_modules:
            migration_steps.append(f"cat {src} >> {target_module}")
            migration_steps.append(f"echo '' >> {target_module}")
            
            rollback_steps.append(f"# Restore {src}")
            rollback_steps.append(f"git checkout -- {src}")
        
        # Update imports
        for src in source_modules:
            old_name = src.replace("/", ".").replace(".py", "")
            new_name = target_module.replace("/", ".").replace(".py", "")
            migration_steps.append(f"find {self.base_path} -name '*.py' -exec sed -i 's/{old_name}/{new_name}/g' {{}} \\;")
        
        # Remove source modules
        for src in source_modules:
            migration_steps.append(f"git rm {src}")
        
        migration = "\n".join(migration_steps)
        rollback = "\n".join(rollback_steps)
        
        return migration, rollback
    
    def generate_extract_migration(
        self,
        source_modules: List[str],
        shared_module: str,
        shared_functions: List[str]
    ) -> Tuple[str, str]:
        """Generate migration for extracting shared functionality."""
        migration_steps = []
        rollback_steps = []
        
        # Create shared module
        migration_steps.append(f"# Create shared module: {shared_module}")
        migration_steps.append(f"mkdir -p $(dirname {shared_module})")
        
        # Extract shared functions
        for func in shared_functions:
            migration_steps.append(f"# Extract {func} from source modules")
        
        # Update imports in source modules
        for src in source_modules:
            module_name = shared_module.replace("/", ".").replace(".py", "")
            migration_steps.append(f"sed -i '1s/^/from {module_name} import {', '.join(shared_functions)}\\n/' {src}")
        
        rollback_steps.append(f"# Remove shared module")
        rollback_steps.append(f"rm -f {shared_module}")
        rollback_steps.append(f"git checkout -- {' '.join(source_modules)}")
        
        migration = "\n".join(migration_steps)
        rollback = "\n".join(rollback_steps)
        
        return migration, rollback


class Architect:
    """
    Meta-level architectural improvement system.
    
    Analyzes AIWorker's own architecture and generates improvement proposals.
    All changes require human approval and have rollback plans.
    """
    
    def __init__(
        self,
        base_path: str = "/opt/aiworker",
        proposals_db: str = "/var/lib/aiworker/architect_proposals.db"
    ):
        self.base_path = Path(base_path)
        self.proposals_db = proposals_db
        self.analyzer = CodeAnalyzer(base_path)
        self.migration_gen = MigrationGenerator(base_path)
        
        self._init_db()
        
        logger.info("Architect initialized")
    
    def _init_db(self):
        """Initialize proposals database."""
        with sqlite3.connect(self.proposals_db) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS proposals (
                    proposal_id TEXT PRIMARY KEY,
                    improvement_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    affected_files TEXT NOT NULL,
                    migration_script TEXT NOT NULL,
                    rollback_script TEXT NOT NULL,
                    test_plan TEXT,
                    required_approvals INTEGER DEFAULT 2,
                    status TEXT DEFAULT 'proposed',
                    approvals TEXT DEFAULT '[]',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            conn.commit()
    
    def analyze_architecture(self) -> Dict[str, Any]:
        """Perform full architectural analysis."""
        logger.info("Starting architectural analysis...")
        
        # Build dependency graph
        dependencies = self.analyzer.build_dependency_graph()
        
        # Find issues
        issues = self.analyzer.find_issues()
        
        # Calculate health score
        health_score = self._calculate_health_score(issues)
        
        # Generate proposals from issues
        proposals = self._generate_proposals_from_issues(issues)
        
        result = {
            "health_score": health_score,
            "modules_analyzed": len(self.analyzer.module_graph),
            "issues_found": len(issues),
            "critical_issues": len([i for i in issues if i.severity == "critical"]),
            "high_issues": len([i for i in issues if i.severity == "high"]),
            "medium_issues": len([i for i in issues if i.severity == "medium"]),
            "low_issues": len([i for i in issues if i.severity == "low"]),
            "issues": [self._issue_to_dict(i) for i in issues[:20]],  # Top 20
            "proposals_generated": len(proposals),
            "dependencies": dependencies,
        }
        
        logger.info(f"Analysis complete: health_score={health_score}, issues={len(issues)}")
        
        return result
    
    def _calculate_health_score(self, issues: List[ArchitecturalIssue]) -> float:
        """Calculate overall architecture health score (0-100)."""
        base_score = 100.0
        
        deductions = {
            "critical": 20,
            "high": 10,
            "medium": 5,
            "low": 2
        }
        
        for issue in issues:
            base_score -= deductions.get(issue.severity, 0)
        
        return max(0.0, base_score)
    
    def _issue_to_dict(self, issue: ArchitecturalIssue) -> Dict[str, Any]:
        """Convert issue to dictionary."""
        return {
            "issue_id": issue.issue_id,
            "metric": issue.metric.value,
            "severity": issue.severity,
            "description": issue.description,
            "affected_modules": issue.affected_modules,
            "suggested_action": issue.suggested_action.value,
            "estimated_effort": issue.estimated_effort,
            "expected_benefit": issue.expected_benefit,
        }
    
    def _generate_proposals_from_issues(
        self,
        issues: List[ArchitecturalIssue]
    ) -> List[ImprovementProposal]:
        """Generate improvement proposals from identified issues."""
        proposals = []
        
        for issue in issues[:5]:  # Generate proposals for top 5 issues
            proposal = self._create_proposal_from_issue(issue)
            if proposal:
                proposals.append(proposal)
                self._save_proposal(proposal)
        
        return proposals
    
    def _create_proposal_from_issue(
        self,
        issue: ArchitecturalIssue
    ) -> Optional[ImprovementProposal]:
        """Create an improvement proposal from an issue."""
        proposal_id = f"arch_{issue.issue_id}"
        
        if issue.suggested_action == ImprovementType.REFACTOR:
            return self._create_refactor_proposal(issue, proposal_id)
        elif issue.suggested_action == ImprovementType.MERGE:
            return self._create_merge_proposal(issue, proposal_id)
        elif issue.suggested_action == ImprovementType.EXTRACT:
            return self._create_extract_proposal(issue, proposal_id)
        
        return None
    
    def _create_refactor_proposal(
        self,
        issue: ArchitecturalIssue,
        proposal_id: str
    ) -> ImprovementProposal:
        """Create a refactoring proposal."""
        module = issue.affected_modules[0]
        
        # Suggest splitting the module
        target_modules = [
            (module.replace(".py", "_core.py"), ["core"]),
            (module.replace(".py", "_utils.py"), ["utils"]),
        ]
        
        migration, rollback = self.migration_gen.generate_refactor_migration(
            module, target_modules
        )
        
        return ImprovementProposal(
            proposal_id=proposal_id,
            improvement_type=ImprovementType.REFACTOR,
            title=f"Refactor {module} for better separation of concerns",
            description=issue.description,
            affected_files=issue.affected_modules,
            migration_script=migration,
            rollback_script=rollback,
            test_plan=f"Run full integration test suite. Verify {module} functionality unchanged.",
            required_approvals=2,
        )
    
    def _create_merge_proposal(
        self,
        issue: ArchitecturalIssue,
        proposal_id: str
    ) -> ImprovementProposal:
        """Create a merge proposal."""
        target = f"aiworker/unified/{issue.issue_id}_merged.py"
        
        migration, rollback = self.migration_gen.generate_merge_migration(
            issue.affected_modules, target
        )
        
        return ImprovementProposal(
            proposal_id=proposal_id,
            improvement_type=ImprovementType.MERGE,
            title=f"Merge redundant modules: {', '.join(issue.affected_modules[:3])}",
            description=issue.description,
            affected_files=issue.affected_modules,
            migration_script=migration,
            rollback_script=rollback,
            test_plan="Verify all merged module functionality works in unified module.",
            required_approvals=2,
        )
    
    def _create_extract_proposal(
        self,
        issue: ArchitecturalIssue,
        proposal_id: str
    ) -> ImprovementProposal:
        """Create an extract proposal."""
        shared_module = f"aiworker/shared/{issue.issue_id}_common.py"
        
        # Infer shared functions from issue description
        shared_functions = ["common_func"]  # Placeholder
        
        migration, rollback = self.migration_gen.generate_extract_migration(
            issue.affected_modules, shared_module, shared_functions
        )
        
        return ImprovementProposal(
            proposal_id=proposal_id,
            improvement_type=ImprovementType.EXTRACT,
            title=f"Extract common functionality from {len(issue.affected_modules)} modules",
            description=issue.description,
            affected_files=issue.affected_modules + [shared_module],
            migration_script=migration,
            rollback_script=rollback,
            test_plan="Verify extracted functions work correctly in all source modules.",
            required_approvals=2,
        )
    
    def _save_proposal(self, proposal: ImprovementProposal):
        """Save proposal to database."""
        import time
        
        with sqlite3.connect(self.proposals_db) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO proposals
                (proposal_id, improvement_type, title, description, affected_files,
                 migration_script, rollback_script, test_plan, required_approvals,
                 status, approvals, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    proposal.proposal_id,
                    proposal.improvement_type.value,
                    proposal.title,
                    proposal.description,
                    json.dumps(proposal.affected_files),
                    proposal.migration_script,
                    proposal.rollback_script,
                    proposal.test_plan,
                    proposal.required_approvals,
                    proposal.status,
                    json.dumps(proposal.approvals),
                    time.time(),
                    time.time(),
                )
            )
            conn.commit()
    
    def get_proposals(self, status: Optional[str] = None) -> List[ImprovementProposal]:
        """Get all proposals, optionally filtered by status."""
        with sqlite3.connect(self.proposals_db) as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM proposals WHERE status = ? ORDER BY created_at DESC",
                    (status,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM proposals ORDER BY created_at DESC"
                ).fetchall()
        
        proposals = []
        for row in rows:
            proposals.append(ImprovementProposal(
                proposal_id=row[0],
                improvement_type=ImprovementType(row[1]),
                title=row[2],
                description=row[3],
                affected_files=json.loads(row[4]),
                migration_script=row[5],
                rollback_script=row[6],
                test_plan=row[7],
                required_approvals=row[8],
                status=row[9],
                approvals=json.loads(row[10]),
            ))
        
        return proposals
    
    def approve_proposal(self, proposal_id: str, approver: str) -> bool:
        """Add approval to a proposal."""
        with sqlite3.connect(self.proposals_db) as conn:
            row = conn.execute(
                "SELECT approvals, required_approvals, status FROM proposals WHERE proposal_id = ?",
                (proposal_id,)
            ).fetchone()
            
            if not row:
                return False
            
            approvals = json.loads(row[0])
            required = row[1]
            status = row[2]
            
            if status != "proposed":
                logger.warning(f"Cannot approve proposal with status: {status}")
                return False
            
            if approver in approvals:
                logger.warning(f"{approver} already approved this proposal")
                return False
            
            approvals.append(approver)
            
            # Check if enough approvals
            new_status = status
            if len(approvals) >= required:
                new_status = "approved"
                logger.info(f"Proposal {proposal_id} fully approved")
            
            conn.execute(
                "UPDATE proposals SET approvals = ?, status = ?, updated_at = ? WHERE proposal_id = ?",
                (json.dumps(approvals), new_status, time.time(), proposal_id)
            )
            conn.commit()
            
            return True
    
    def execute_proposal(self, proposal_id: str) -> bool:
        """
        Execute an approved proposal.
        
        WARNING: This makes actual changes to the codebase.
        Ensure rollback script is tested first.
        """
        proposals = self.get_proposals(status="approved")
        proposal = next((p for p in proposals if p.proposal_id == proposal_id), None)
        
        if not proposal:
            logger.error(f"Proposal {proposal_id} not found or not approved")
            return False
        
        logger.info(f"Executing proposal: {proposal.title}")
        
        # Create backup
        backup_dir = f"/var/backups/aiworker/architect/{proposal_id}_{int(time.time())}"
        os.makedirs(backup_dir, exist_ok=True)
        
        # Run migration script
        try:
            # Save migration script
            migration_path = f"{backup_dir}/migration.sh"
            with open(migration_path, "w") as f:
                f.write(proposal.migration_script)
            os.chmod(migration_path, 0o755)
            
            # Execute
            result = subprocess.run(
                ["bash", migration_path],
                cwd=self.base_path,
                capture_output=True,
                text=True,
                timeout=300
            )
            
            if result.returncode == 0:
                # Update status
                with sqlite3.connect(self.proposals_db) as conn:
                    conn.execute(
                        "UPDATE proposals SET status = ?, updated_at = ? WHERE proposal_id = ?",
                        ("deployed", time.time(), proposal_id)
                    )
                    conn.commit()
                
                logger.info(f"Proposal {proposal_id} executed successfully")
                return True
            else:
                logger.error(f"Migration failed: {result.stderr}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to execute proposal: {e}")
            return False
    
    def rollback_proposal(self, proposal_id: str) -> bool:
        """Rollback a deployed proposal."""
        proposals = self.get_proposals(status="deployed")
        proposal = next((p for p in proposals if p.proposal_id == proposal_id), None)
        
        if not proposal:
            logger.error(f"Proposal {proposal_id} not found or not deployed")
            return False
        
        logger.info(f"Rolling back proposal: {proposal.title}")
        
        try:
            # Save and execute rollback script
            rollback_path = f"/tmp/rollback_{proposal_id}.sh"
            with open(rollback_path, "w") as f:
                f.write(proposal.rollback_script)
            os.chmod(rollback_path, 0o755)
            
            result = subprocess.run(
                ["bash", rollback_path],
                cwd=self.base_path,
                capture_output=True,
                text=True,
                timeout=300
            )
            
            if result.returncode == 0:
                with sqlite3.connect(self.proposals_db) as conn:
                    conn.execute(
                        "UPDATE proposals SET status = ?, updated_at = ? WHERE proposal_id = ?",
                        ("rolled_back", time.time(), proposal_id)
                    )
                    conn.commit()
                
                logger.info(f"Proposal {proposal_id} rolled back successfully")
                return True
            else:
                logger.error(f"Rollback failed: {result.stderr}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to rollback proposal: {e}")
            return False
    
    def get_stats(self) -> Dict[str, Any]:
        """Get architect statistics."""
        with sqlite3.connect(self.proposals_db) as conn:
            total = conn.execute("SELECT COUNT(*) FROM proposals").fetchone()[0]
            by_status = {}
            for status in ["proposed", "approved", "deployed", "rolled_back"]:
                count = conn.execute(
                    "SELECT COUNT(*) FROM proposals WHERE status = ?",
                    (status,)
                ).fetchone()[0]
                by_status[status] = count
        
        return {
            "total_proposals": total,
            "by_status": by_status,
            "modules_analyzed": len(self.analyzer.module_graph),
            "health_score": self._calculate_health_score(self.analyzer.find_issues()),
        }
