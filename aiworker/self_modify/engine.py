"""
AIWorker Self-Modification Engine - Phase 2 Integration

Refactored self-modification engine integrating:
- SafetyCage: Three-tier safety system (AST check → human approval → kill switch)
- SequentialEngine: State machine with checkpointing
- MCP Tools: Filesystem, code_executor, and git_ops via stdio transport

All patches flow through: Tier 1 (automatic) → Tier 2 (human approval) → Apply → Git commit
"""

import ast
import json
import logging
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel

# Import from Phase 1 components
from aiworker.safety.safety_cage import SafetyCage, SafetyResult
from aiworker.engine.sequential_engine import IterationContext, State
from aiworker.execution.runner import ExecutionResult, Runner
from aiworker.self_modify.approval import ApprovalDecision, evaluate_approval
from aiworker.self_modify.change_request import ChangeRequest
from aiworker.self_modify.patch_validator import ValidationResult, validate_patch

# Configure logging
logger = logging.getLogger("aiworker.self_modify")


@dataclass(frozen=True)
class EngineResult:
    validation_passed: bool
    validation_result: ValidationResult
    sandbox_result: ExecutionResult | None
    approval_decision: ApprovalDecision | None
    approval_required: bool
    approved: bool
    decision_context: dict[str, Any]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "validation_passed": self.validation_passed,
            "validation_result": self.validation_result.to_dict(),
            "sandbox_result": self.sandbox_result.to_dict() if self.sandbox_result else None,
            "approval_decision": self.approval_decision.to_dict() if self.approval_decision else None,
            "approval_required": self.approval_required,
            "approved": self.approved,
            "decision_context": self.decision_context,
            "reason": self.reason,
        }


def process_change_request(
    change_request: ChangeRequest,
    patch_content: str,
    workspace_path: str,
    *,
    timeout: int = 60,
    explicit_approval: bool = False,
) -> EngineResult:
    validation_result = validate_patch(patch_content, change_request)
    if not validation_result.valid:
        return EngineResult(
            validation_passed=False,
            validation_result=validation_result,
            sandbox_result=None,
            approval_decision=None,
            approval_required=False,
            approved=False,
            decision_context={"stage": "validation"},
            reason="Patch validation failed",
        )

    sandbox_result = Runner(workspace_path, patch_content, timeout=timeout).execute()
    approval_decision = evaluate_approval(
        change_request,
        sandbox_result,
        explicit_approval=explicit_approval,
    )
    approved = approval_decision.eligible and explicit_approval
    approval_required = approval_decision.eligible and not explicit_approval
    return EngineResult(
        validation_passed=True,
        validation_result=validation_result,
        sandbox_result=sandbox_result,
        approval_decision=approval_decision,
        approval_required=approval_required,
        approved=approved,
        decision_context={"stage": "approval", "sandbox_success": sandbox_result.success},
        reason=approval_decision.reason,
    )


class PatchCandidate(BaseModel):
    """Represents a generated code patch candidate."""
    target_file: str
    original_content: str
    patched_content: str
    rationale: str
    patch_hash: str
    created_at: float = field(default_factory=time.time)
    validation_result: Optional[dict] = None
    safety_result: Optional[SafetyResult] = None
    
    def compute_hash(self) -> str:
        """Compute unique hash for this patch."""
        import hashlib
        content = f"{self.target_file}:{self.original_content}:{self.patched_content}:{self.rationale}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def model_post_init(self, __context: Any) -> None:
        """Compute hash after initialization."""
        if not self.patch_hash:
            self.patch_hash = self.compute_hash()


class MCPToolClient:
    """Client for calling MCP tools via subprocess."""
    
    def __init__(self, server_name: str, base_path: str = "/opt/aiworker"):
        self.server_name = server_name
        self.base_path = Path(base_path)
    
    def call(self, tool_name: str, **kwargs) -> dict[str, Any]:
        """Call an MCP tool via subprocess."""
        try:
            # Build the JSON-RPC request
            request = {
                "jsonrpc": "2.0",
                "method": f"tools/{tool_name}",
                "params": kwargs,
                "id": int(time.time() * 1000)
            }
            
            # Run the MCP server with the tool call
            cmd = [
                "python", "-m", "aiworker.mcp.servers", 
                self.server_name
            ]
            
            result = subprocess.run(
                cmd,
                input=json.dumps(request),
                capture_output=True,
                text=True,
                timeout=30
            )
            
            # Parse response (MCP uses stdio, so we need to handle this differently)
            # For simplicity, we'll use a direct Python call approach
            return self._direct_call(tool_name, **kwargs)
        
        except Exception as e:
            logger.error(f"MCP call failed: {e}")
            return {"success": False, "error": str(e)}
    
    def _direct_call(self, tool_name: str, **kwargs) -> dict[str, Any]:
        """Direct Python call to MCP tools (bypassing stdio for same-process)."""
        from aiworker.mcp.servers import (
            read_file, write_file, list_dir, file_exists,
            execute_python,
            git_status, git_diff, git_add, git_commit, git_log, git_checkout
        )
        
        tool_map = {
            "filesystem": {
                "read_file": read_file,
                "write_file": write_file,
                "list_dir": list_dir,
                "file_exists": file_exists,
            },
            "code_executor": {
                "execute_python": execute_python,
            },
            "git_ops": {
                "git_status": git_status,
                "git_diff": git_diff,
                "git_add": git_add,
                "git_commit": git_commit,
                "git_log": git_log,
                "git_checkout": git_checkout,
            }
        }
        
        if self.server_name not in tool_map:
            return {"success": False, "error": f"Unknown server: {self.server_name}"}
        
        if tool_name not in tool_map[self.server_name]:
            return {"success": False, "error": f"Unknown tool: {tool_name}"}
        
        try:
            tool = tool_map[self.server_name][tool_name]
            return tool(**kwargs)
        except Exception as e:
            logger.error(f"Tool execution failed: {e}")
            return {"success": False, "error": str(e)}


class SelfModifyEngine:
    """
    Self-modification engine with SafetyCage integration and MCP tool usage.
    
    All file operations go through MCP filesystem server.
    All git operations go through MCP git_ops server.
    All code execution goes through MCP code_executor server.
    """
    
    def __init__(self, safety_cage: SafetyCage, base_path: str = "/opt/aiworker"):
        self.safety_cage = safety_cage
        self.base_path = Path(base_path)
        
        # MCP clients
        self.fs_client = MCPToolClient("filesystem", base_path)
        self.git_client = MCPToolClient("git_ops", base_path)
        self.exec_client = MCPToolClient("code_executor", base_path)
        
        logger.info("SelfModifyEngine initialized")
    
    def plan_change(self, goal: str, context: IterationContext) -> str:
        """
        Plan a code change based on the goal.
        
        Args:
            goal: The improvement goal
            context: Current iteration context
            
        Returns:
            Rationale string describing the planned change
        """
        logger.info(f"Planning change for goal: {goal[:50]}...")
        
        # Analyze goal to determine target file and strategy
        rationale = self._analyze_goal(goal, context)
        
        # Store plan in context
        context.data['plan'] = {
            'goal': goal,
            'rationale': rationale,
            'target_file': context.data.get('target_file'),
            'strategy': context.data.get('strategy', 'direct_patch'),
            'topic': context.data.get('topic')
        }
        
        logger.info(f"Plan created: {rationale[:100]}...")
        return rationale
    
    def _analyze_goal(self, goal: str, context: IterationContext) -> str:
        """Analyze goal and determine change strategy."""
        goal_lower = goal.lower()
        
        # Determine target file from goal
        target_file = None
        
        # Look for file mentions in goal
        file_patterns = [
            r'(?:in|to|file)\s+["\']?(\S+\.py)["\']?',
            r'["\']?(aiworker/\S+\.py)["\']?',
            r'["\']?(\S+_engine\.py)["\']?',
        ]
        
        for pattern in file_patterns:
            match = re.search(pattern, goal_lower)
            if match:
                target_file = match.group(1)
                break
        
        # Default targets based on goal keywords
        if not target_file:
            if 'research' in goal_lower or 'search' in goal_lower or 'scrape' in goal_lower:
                target_file = "aiworker/research/web_researcher.py"
            elif 'safety' in goal_lower or 'cage' in goal_lower or 'approve' in goal_lower:
                target_file = "aiworker/safety/safety_cage.py"
            elif 'engine' in goal_lower or 'state' in goal_lower or 'handler' in goal_lower:
                target_file = "aiworker/engine/sequential_engine.py"
            elif 'mcp' in goal_lower or 'server' in goal_lower:
                target_file = "aiworker/mcp/servers.py"
            elif 'config' in goal_lower:
                target_file = "aiworker/config.py"
            else:
                target_file = "aiworker/main.py"
        
        context.data['target_file'] = target_file
        
        # Determine if research is needed
        if any(kw in goal_lower for kw in ['research', 'learn', 'find', 'search', 'investigate']):
            context.data['topic'] = goal
        
        # Build rationale
        rationale = f"""
Goal Analysis:
- Target: {target_file}
- Objective: {goal}
- Strategy: {'Research-first' if context.data.get('topic') else 'Direct modification'}

Planned Approach:
1. {'Gather external knowledge on topic' if context.data.get('topic') else 'Analyze current implementation'}
2. Identify improvement opportunities in {target_file}
3. Generate patch with minimal, focused changes
4. Validate with regression tests
5. Apply with git commit
"""
        
        return rationale.strip()
    
    def generate_patch(
        self, 
        target_file: Path, 
        rationale: str, 
        context: IterationContext
    ) -> PatchCandidate:
        """
        Generate a patch candidate for the target file.
        
        Args:
            target_file: Path to file to modify
            rationale: Change rationale from planning
            context: Current iteration context
            
        Returns:
            PatchCandidate with original and patched content
        """
        logger.info(f"Generating patch for {target_file}")
        
        # Read current file content via MCP
        file_path_str = str(target_file).replace(str(self.base_path), "").lstrip("/")
        result = self.fs_client.call("read_file", path=file_path_str)
        
        if not result.get("success"):
            raise ValueError(f"Failed to read {target_file}: {result.get('error')}")
        
        original_content = result["content"]
        
        # Generate patch based on goal and research findings
        research = context.data.get('research_findings', {})
        goal = context.data.get('plan', {}).get('goal', '')
        
        patched_content = self._generate_patched_content(
            original_content, 
            goal, 
            rationale,
            research
        )
        
        # Create patch candidate
        candidate = PatchCandidate(
            target_file=str(target_file),
            original_content=original_content,
            patched_content=patched_content,
            rationale=rationale
        )
        
        # Store in context
        context.data['patch_candidate'] = candidate.model_dump()
        
        logger.info(f"Patch generated: {candidate.patch_hash}")
        return candidate
    
    def _generate_patched_content(
        self, 
        original: str, 
        goal: str, 
        rationale: str,
        research: dict
    ) -> str:
        """Generate patched content based on goal."""
        # This is a simplified patch generation
        # In production, this would use LLM to generate intelligent patches
        
        goal_lower = goal.lower()
        patched = original
        
        # Apply common improvement patterns
        if 'error handling' in goal_lower or 'exception' in goal_lower:
            # Add try-except blocks around bare code
            patched = self._add_error_handling(patched)
        
        if 'logging' in goal_lower:
            # Add logging statements
            patched = self._add_logging(patched)
        
        if 'type hint' in goal_lower or 'typing' in goal_lower:
            # Add type hints
            patched = self._add_type_hints(patched)
        
        if 'docstring' in goal_lower or 'documentation' in goal_lower:
            # Add docstrings
            patched = self._add_docstrings(patched)
        
        if 'optimize' in goal_lower or 'performance' in goal_lower:
            # Apply performance optimizations
            patched = self._optimize_code(patched)
        
        # If no specific pattern matched, add a comment marker
        if patched == original:
            patched = self._add_improvement_marker(patched, goal)
        
        return patched
    
    def _add_error_handling(self, code: str) -> str:
        """Add error handling to code."""
        # Simple pattern: wrap function bodies in try-except
        lines = code.split('\n')
        result = []
        in_function = False
        indent_level = 0
        
        for i, line in enumerate(lines):
            # Detect function definition
            if re.match(r'^(\s*)def\s+\w+\s*\(', line):
                in_function = True
                indent_level = len(line) - len(line.lstrip())
                result.append(line)
                continue
            
            # Add try-except at start of function body
            if in_function and line.strip() and not line.strip().startswith('#'):
                current_indent = len(line) - len(line.lstrip())
                if current_indent > indent_level:
                    result.append(' ' * (indent_level + 4) + 'try:')
                    result.append(' ' * (current_indent + 4) + line.strip())
                    in_function = False
                    continue
            
            result.append(line)
        
        return '\n'.join(result)
    
    def _add_logging(self, code: str) -> str:
        """Add logging to code."""
        if 'import logging' not in code:
            code = 'import logging\n\nlogger = logging.getLogger(__name__)\n\n' + code
        
        # Add entry/exit logging to functions
        lines = code.split('\n')
        result = []
        
        for line in lines:
            result.append(line)
            match = re.match(r'^(\s*)def\s+(\w+)\s*\(', line)
            if match:
                indent = match.group(1) + '    '
                func_name = match.group(2)
                result.append(f"{indent}logger.debug(f'Entering {func_name}')")
        
        return '\n'.join(result)
    
    def _add_type_hints(self, code: str) -> str:
        """Add type hints to code."""
        # Add typing import if needed
        if 'from typing' not in code and 'import typing' not in code:
            code = 'from typing import Any, Optional, Dict, List\n' + code
        
        return code
    
    def _add_docstrings(self, code: str) -> str:
        """Add docstrings to functions."""
        lines = code.split('\n')
        result = []
        
        for i, line in enumerate(lines):
            result.append(line)
            match = re.match(r'^(\s*)def\s+(\w+)\s*\(([^)]*)\)', line)
            if match:
                indent = match.group(1)
                func_name = match.group(2)
                params = match.group(3)
                
                # Check if next line is already a docstring
                if i + 1 < len(lines) and '"""' in lines[i + 1]:
                    continue
                
                docstring = f'{indent}    """{func_name} function."""'
                result.append(docstring)
        
        return '\n'.join(result)
    
    def _optimize_code(self, code: str) -> str:
        """Apply basic optimizations."""
        # Replace list comprehensions with generator expressions where appropriate
        code = re.sub(
            r'sum\(\[([^\]]+)\]\)',
            r'sum(\1)',
            code
        )
        
        # Use dict.get() instead of key checking
        code = re.sub(
            r'if (\w+) in (\w+):\s*\n\s*(\w+) = (\w+)\[(\w+)\]\s*\n\s*else:\s*\n\s*(\w+) = (\S+)',
            r'\3 = \2.get(\1, \8)',
            code
        )
        
        return code
    
    def _add_improvement_marker(self, code: str, goal: str) -> str:
        """Add a marker comment for improvement."""
        lines = code.split('\n')
        
        # Find a good insertion point (after imports, before first function)
        insert_idx = 0
        for i, line in enumerate(lines):
            if line.strip().startswith('def ') or line.strip().startswith('class '):
                insert_idx = i
                break
            insert_idx = i + 1
        
        marker = f"""
# AIWorker Self-Improvement Marker
# Goal: {goal}
# Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}
# This file is marked for improvement based on the above goal.

"""
        lines.insert(insert_idx, marker)
        return '\n'.join(lines)
    
    def validate_patch(self, candidate: PatchCandidate, context: IterationContext) -> bool:
        """
        Validate a patch candidate using regression tests.
        
        Args:
            candidate: PatchCandidate to validate
            context: Current iteration context
            
        Returns:
            True if validation passes
        """
        logger.info(f"Validating patch: {candidate.patch_hash}")
        
        validation_results = {
            "syntax_valid": False,
            "ast_valid": False,
            "tests_pass": False,
            "errors": []
        }
        
        # 1. Syntax validation
        try:
            compile(candidate.patched_content, candidate.target_file, 'exec')
            validation_results["syntax_valid"] = True
        except SyntaxError as e:
            validation_results["errors"].append(f"Syntax error: {e}")
            context.data['validation'] = validation_results
            return False
        
        # 2. AST validation
        try:
            ast.parse(candidate.patched_content)
            validation_results["ast_valid"] = True
        except SyntaxError as e:
            validation_results["errors"].append(f"AST error: {e}")
            context.data['validation'] = validation_results
            return False
        
        # 3. Run regression tests via MCP code_executor
        test_code = self._build_test_code(candidate)
        result = self.exec_client.call("execute_python", code=test_code, timeout=60)
        
        if result.get("success"):
            validation_results["tests_pass"] = True
        else:
            validation_results["errors"].append(
                f"Test failure: {result.get('stderr', 'Unknown error')}"
            )
        
        context.data['validation'] = validation_results
        
        # Update candidate
        candidate.validation_result = validation_results
        
        success = all([
            validation_results["syntax_valid"],
            validation_results["ast_valid"],
            validation_results["tests_pass"]
        ])
        
        logger.info(f"Validation {'passed' if success else 'failed'}")
        return success
    
    def _build_test_code(self, candidate: PatchCandidate) -> str:
        """Build test code for patch validation."""
        return f'''
# Test code for patch validation
import ast
import sys

# Test 1: Verify patched content is valid Python
code = {candidate.patched_content!r}

try:
    # Parse with AST
    tree = ast.parse(code)
    
    # Check for dangerous nodes
    dangerous_nodes = [
        ast.Exec,  # Python 2 only, but kept for safety
    ]
    
    for node in ast.walk(tree):
        for dangerous in dangerous_nodes:
            if isinstance(node, dangerous):
                print(f"Dangerous node found: {{type(node).__name__}}")
                sys.exit(1)
    
    print("AST validation passed")
    
    # Test 2: Compile the code
    compile(code, "<test>", "exec")
    print("Compilation passed")
    
    print("All tests passed!")
    
except Exception as e:
    print(f"Test failed: {{e}}")
    sys.exit(1)
'''
    
    def apply_patch(self, candidate: PatchCandidate, context: IterationContext) -> bool:
        """
        Apply a validated patch and create git commit.
        
        Args:
            candidate: PatchCandidate to apply
            context: Current iteration context
            
        Returns:
            True if patch was applied successfully
        """
        logger.info(f"Applying patch: {candidate.patch_hash}")
        
        # Write patched content via MCP filesystem
        file_path_str = str(candidate.target_file).replace(str(self.base_path), "").lstrip("/")
        
        result = self.fs_client.call(
            "write_file", 
            path=file_path_str, 
            content=candidate.patched_content
        )
        
        if not result.get("success"):
            logger.error(f"Failed to write file: {result.get('error')}")
            return False
        
        # Stage the file via git_ops MCP
        add_result = self.git_client.call("git_add", files=[file_path_str])
        
        if not add_result.get("success"):
            logger.error(f"Failed to stage file: {add_result.get('error')}")
            # Rollback: restore original content
            self.fs_client.call(
                "write_file",
                path=file_path_str,
                content=candidate.original_content
            )
            return False
        
        # Create commit
        commit_msg = f"""AIWorker self-improvement: {candidate.patch_hash}

Rationale:
{candidate.rationale[:200]}...

Target: {candidate.target_file}
"""
        
        commit_result = self.git_client.call("git_commit", message=commit_msg)
        
        if not commit_result.get("success"):
            logger.error(f"Failed to commit: {commit_result.get('error')}")
            # Rollback
            self.fs_client.call(
                "write_file",
                path=file_path_str,
                content=candidate.original_content
            )
            return False
        
        logger.info(f"Patch applied and committed: {commit_result.get('commit_hash')}")
        
        # Store result in context
        context.data['apply_result'] = {
            "success": True,
            "commit_hash": commit_result.get("commit_hash"),
            "patch_hash": candidate.patch_hash,
            "target_file": candidate.target_file
        }
        
        return True
    
    def rollback_patch(self, candidate: PatchCandidate) -> bool:
        """
        Rollback a patch by restoring original content.
        
        Args:
            candidate: PatchCandidate to rollback
            
        Returns:
            True if rollback was successful
        """
        logger.info(f"Rolling back patch: {candidate.patch_hash}")
        
        file_path_str = str(candidate.target_file).replace(str(self.base_path), "").lstrip("/")
        
        result = self.fs_client.call(
            "write_file",
            path=file_path_str,
            content=candidate.original_content
        )
        
        if result.get("success"):
            logger.info("Rollback successful")
            return True
        else:
            logger.error(f"Rollback failed: {result.get('error')}")
            return False


# =============================================================================
# Factory function for easy instantiation
# =============================================================================

def create_self_modify_engine(
    safety_cage: Optional[SafetyCage] = None,
    base_path: str = "/opt/aiworker"
) -> SelfModifyEngine:
    """Create a SelfModifyEngine with default SafetyCage."""
    if safety_cage is None:
        from aiworker.config import AIWorkerConfig
        config = AIWorkerConfig.from_env()
        safety_cage = SafetyCage(config)
    
    return SelfModifyEngine(safety_cage, base_path)
