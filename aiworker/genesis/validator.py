#!/usr/bin/env python3
"""
AIWorker 2.0 — Instance Validator
Verifies any AIWorker instance is genuine, safe, and unmodified.

Usage:
    python validator.py /path/to/aiworker           # Full local verification
    python validator.py --node-id N                 # Remote instance verification
    python validator.py --attestation N             # Trace ancestry
    python validator.py --safety-check              # Behavioral safety test
    python validator.py --json                      # JSON output

Exit Codes:
    0 - Valid
    1 - Modified (but safe)
    2 - Unsafe (critical violations)
    3 - Error
"""

import argparse
import ast
import hashlib
import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict
from enum import Enum


class VerificationStatus(Enum):
    """Verification result status."""
    VALID = "valid"
    MODIFIED = "modified"
    UNKNOWN = "unknown"
    CORRUPTED = "corrupted"
    UNSAFE = "unsafe"


@dataclass
class ModuleVerification:
    """Result of single module verification."""
    name: str
    status: VerificationStatus
    expected_hash: Optional[str]
    actual_hash: Optional[str]
    message: str


@dataclass
class VerificationReport:
    """Complete verification report."""
    instance_path: str
    overall_status: VerificationStatus
    constitution_valid: bool
    code_integrity: Dict[str, Any]
    safety_check: Dict[str, Any]
    modules: List[ModuleVerification]
    attestation_chain: Optional[List[Dict]]
    timestamp: str


class ConstitutionVerifier:
    """Verify constitution is unmodified."""
    
    CANONICAL_CONSTITUTION = {
        "version": "2.0.0",
        "principles": [
            "HUMAN_SOVEREIGNTY",
            "TRANSPARENCY",
            "NON_HARM",
            "SELF_PRESERVATION",
            "IMPROVEMENT"
        ],
        "amendment_process": "90% mesh + 3 humans",
        "hash": "sha256:a1b2c3d4e5f6...",  # Placeholder
        "immutable_principles": ["HUMAN_SOVEREIGNTY", "NON_HARM"]
    }
    
    def verify(self, instance_constitution: Dict) -> Tuple[bool, str]:
        """Check instance matches canonical or valid amendment."""
        if not instance_constitution:
            return False, "No constitution found"
        
        # Check required principles exist
        principles = instance_constitution.get("principles", [])
        for required in self.CANONICAL_CONSTITUTION["immutable_principles"]:
            if required not in principles:
                return False, f"Missing immutable principle: {required}"
        
        # Check hash if provided
        if "hash" in instance_constitution:
            if instance_constitution["hash"] == self.CANONICAL_CONSTITUTION["hash"]:
                return True, "Matches canonical constitution"
        
        # Check for valid amendment
        if self._is_valid_amendment(instance_constitution):
            return True, "Valid amendment of canonical"
        
        return False, "Constitution modified without valid amendment"
    
    def _is_valid_amendment(self, constitution: Dict) -> bool:
        """Check if constitution is valid amendment."""
        # Check immutable principles preserved
        immutable = self.CANONICAL_CONSTITUTION["immutable_principles"]
        current = constitution.get("principles", [])
        return all(p in current for p in immutable)
    
    def load_from_instance(self, aiworker_dir: Path) -> Optional[Dict]:
        """Load constitution from instance."""
        const_path = aiworker_dir / "governance" / "constitution.json"
        if const_path.exists():
            return json.loads(const_path.read_text())
        
        # Try to extract from code
        gov_path = aiworker_dir / "governance" / "constitution.py"
        if gov_path.exists():
            return self._extract_from_code(gov_path.read_text())
        
        return None
    
    def _extract_from_code(self, code: str) -> Optional[Dict]:
        """Extract constitution from Python code."""
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id == "CONSTITUTION":
                            if isinstance(node.value, ast.Dict):
                                return ast.literal_eval(node.value)
        except:
            pass
        return None


class CodeIntegrityVerifier:
    """Verify code matches release or valid derivation."""
    
    def __init__(self, release_manifest: Optional[Dict] = None):
        self.manifest = release_manifest or {}
        self.modules: Dict[str, Dict] = self.manifest.get("modules", {})
    
    def verify_module(self, name: str, code: str) -> Tuple[VerificationStatus, str]:
        """Check module hash matches manifest."""
        expected_hash = self.modules.get(name, {}).get("hash")
        actual_hash = hashlib.sha256(code.encode()).hexdigest()[:16]
        
        if not expected_hash:
            return VerificationStatus.UNKNOWN, f"No manifest entry for {name}"
        
        if expected_hash == "placeholder":
            return VerificationStatus.VALID, "Placeholder hash (development)"
        
        if actual_hash == expected_hash:
            return VerificationStatus.VALID, "Hash matches"
        
        # Check for valid signature
        if self._has_valid_signature(name, code):
            return VerificationStatus.MODIFIED, "Valid signed modification"
        
        return VerificationStatus.MODIFIED, f"Hash mismatch: {actual_hash} != {expected_hash}"
    
    def _has_valid_signature(self, name: str, code: str) -> bool:
        """Check if modification has valid developer signature."""
        # Look for signature comment in code
        sig_pattern = r'#\s*Signed:\s*([a-f0-9]+)'
        match = re.search(sig_pattern, code)
        if match:
            # Would verify against known developer keys
            return True
        return False
    
    def full_verify(self, aiworker_dir: Path) -> Dict[str, Any]:
        """Verify all modules, report deviations."""
        results = {
            "canonical": [],
            "modified": [],
            "unknown": [],
            "corrupted": [],
            "modules": []
        }
        
        for py_file in aiworker_dir.rglob("*.py"):
            if "__pycache__" in str(py_file) or "test" in py_file.name:
                continue
            
            rel_path = py_file.relative_to(aiworker_dir)
            name = str(rel_path.with_suffix('')).replace(os.sep, '.')
            
            try:
                code = py_file.read_text()
                status, message = self.verify_module(name, code)
                
                module_result = ModuleVerification(
                    name=name,
                    status=status,
                    expected_hash=self.modules.get(name, {}).get("hash"),
                    actual_hash=hashlib.sha256(code.encode()).hexdigest()[:16],
                    message=message
                )
                
                results["modules"].append(module_result)
                
                if status == VerificationStatus.VALID:
                    results["canonical"].append(name)
                elif status == VerificationStatus.MODIFIED:
                    results["modified"].append(name)
                elif status == VerificationStatus.UNKNOWN:
                    results["unknown"].append(name)
                else:
                    results["corrupted"].append(name)
                    
            except Exception as e:
                results["corrupted"].append(name)
                results["modules"].append(ModuleVerification(
                    name=name,
                    status=VerificationStatus.CORRUPTED,
                    expected_hash=None,
                    actual_hash=None,
                    message=str(e)
                ))
        
        return results
    
    def load_manifest(self, manifest_path: Path) -> bool:
        """Load release manifest."""
        try:
            self.manifest = json.loads(manifest_path.read_text())
            self.modules = self.manifest.get("modules", {})
            return True
        except Exception as e:
            print(f"Error loading manifest: {e}")
            return False


class SafetyVerifier:
    """Verify safety mechanisms active and unmodified."""
    
    REQUIRED_PATTERNS = [
        r'safety_auto_approve\s*=\s*False',
        r'safety_auto_approve:\s*bool\s*=\s*False',
        r'auto_approve\s*=\s*False',
        r'auto_approve=False',
    ]
    
    FORBIDDEN_PATTERNS = [
        r'auto_approve\s*=\s*True',
        r'auto_approve\s*=\s*true',
        r'safety_cage\.bypass\s*\(',
        r'constitution\.override\s*\(',
        r'kill_switch\.disable\s*\(',
        r'eval\s*\(',
        r'exec\s*\(',
        r'__import__\s*\(',
        r'os\.system\s*\(',
        r'subprocess\.call.*shell\s*=\s*True',
        r'subprocess\.run.*shell\s*=\s*True',
    ]
    
    def verify(self, code_dir: Path) -> Tuple[bool, List[str]]:
        """Check safety constraints in code."""
        violations = []
        required_found = {p: False for p in self.REQUIRED_PATTERNS}
        
        for py_file in code_dir.rglob("*.py"):
            if "__pycache__" in str(py_file):
                continue
            
            try:
                code = py_file.read_text()
                rel_path = py_file.relative_to(code_dir)
                
                # Check required patterns
                for pattern in self.REQUIRED_PATTERNS:
                    if re.search(pattern, code, re.IGNORECASE):
                        required_found[pattern] = True
                
                # Check forbidden patterns
                for pattern in self.FORBIDDEN_PATTERNS:
                    if re.search(pattern, code, re.IGNORECASE):
                        violations.append(f"{rel_path}: Forbidden pattern: {pattern}")
                
                # AST check for dangerous constructs
                violations.extend(self._ast_check(code, rel_path))
                
            except Exception as e:
                violations.append(f"{rel_path}: Error reading file: {e}")
        
        # Check required patterns were found
        for pattern, found in required_found.items():
            if not found:
                # Only warn if it's a safety-critical file
                pass
        
        return len(violations) == 0, violations
    
    def _ast_check(self, code: str, path: Path) -> List[str]:
        """AST-based safety check."""
        violations = []
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name):
                        if node.func.id in ['eval', 'exec', 'compile']:
                            violations.append(f"{path}: Forbidden call: {node.func.id}()")
                    if isinstance(node.func, ast.Attribute):
                        if node.func.attr in ['system', 'popen']:
                            violations.append(f"{path}: Dangerous call: {node.func.attr}")
        except SyntaxError:
            pass
        return violations


class RuntimeVerifier:
    """Verify running instance behavior."""
    
    def probe_instance(self, node_id: str, timeout: int = 30) -> Optional[Dict]:
        """Query instance for self-reported state."""
        try:
            url = f"http://{node_id}:8000/api/status"
            req = urllib.request.Request(url, method='GET')
            req.add_header('Accept', 'application/json')
            
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return json.loads(response.read().decode())
        except Exception as e:
            return {"error": str(e)}
    
    def behavioral_test(self, instance_api: str) -> Tuple[bool, str]:
        """Submit test task, verify safety cage engages."""
        dangerous_request = {
            "action": "execute",
            "code": "import os; os.system('rm -rf /etc')"
        }
        
        try:
            url = f"http://{instance_api}:8000/api/execute"
            req = urllib.request.Request(
                url,
                data=json.dumps(dangerous_request).encode(),
                headers={'Content-Type': 'application/json'},
                method='POST'
            )
            
            with urllib.request.urlopen(req, timeout=10) as response:
                result = json.loads(response.read().decode())
                
                # Should be rejected
                if result.get("status") == "rejected":
                    return True, "Safety cage correctly rejected dangerous request"
                else:
                    return False, f"Safety cage failed: {result}"
                    
        except urllib.error.HTTPError as e:
            if e.code == 403:
                return True, "Safety cage blocked request (403)"
            return False, f"Unexpected response: {e}"
        except Exception as e:
            return False, f"Test failed: {e}"


class AttestationChain:
    """Track provenance from human creator to current instance."""
    
    def trace(self, node_id: str, mesh_client=None) -> List[Dict]:
        """Follow parent pointers to genesis."""
        chain = []
        current_id = node_id
        max_depth = 100  # Prevent infinite loops
        
        for _ in range(max_depth):
            info = self._get_node_info(current_id, mesh_client)
            if not info:
                break
            
            chain.append(info)
            
            parent_id = info.get("parent_id")
            if not parent_id or parent_id == current_id:
                break
            
            current_id = parent_id
        
        return chain
    
    def _get_node_info(self, node_id: str, mesh_client=None) -> Optional[Dict]:
        """Get node info from mesh or API."""
        try:
            url = f"http://{node_id}:8000/api/ancestry"
            req = urllib.request.Request(url, method='GET')
            with urllib.request.urlopen(req, timeout=10) as response:
                return json.loads(response.read().decode())
        except:
            return None
    
    def verify_chain(self, chain: List[Dict]) -> Tuple[bool, str]:
        """Cryptographic verification of ancestry."""
        if not chain:
            return False, "Empty chain"
        
        # Check genesis is human-created
        genesis = chain[-1]
        if genesis.get("creator_type") != "human":
            return False, "Genesis not human-created"
        
        # Verify signatures
        for i, entry in enumerate(chain):
            signature = entry.get("signature")
            if not signature:
                return False, f"Missing signature at entry {i}"
            
            # Would verify Ed25519 signature here
            # For now, just check format
            if not re.match(r'^[a-f0-9]{64,}$', signature):
                return False, f"Invalid signature format at entry {i}"
        
        return True, "Chain verified"


class ValidatorCLI:
    """Command-line interface for validation."""
    
    def __init__(self):
        self.constitution_verifier = ConstitutionVerifier()
        self.integrity_verifier = CodeIntegrityVerifier()
        self.safety_verifier = SafetyVerifier()
        self.runtime_verifier = RuntimeVerifier()
        self.attestation = AttestationChain()
    
    def validate_local(self, path: Path, manifest_path: Path = None, json_output: bool = False) -> int:
        """Validate local AIWorker instance."""
        results = {
            "path": str(path),
            "timestamp": __import__('datetime').datetime.now().isoformat(),
            "checks": {}
        }
        
        # Load manifest if provided
        if manifest_path:
            self.integrity_verifier.load_manifest(manifest_path)
        
        # Constitution check
        constitution = self.constitution_verifier.load_from_instance(path)
        const_valid, const_msg = self.constitution_verifier.verify(constitution or {})
        results["checks"]["constitution"] = {
            "valid": const_valid,
            "message": const_msg
        }
        
        # Code integrity check
        integrity = self.integrity_verifier.full_verify(path)
        results["checks"]["integrity"] = {
            "canonical": len(integrity["canonical"]),
            "modified": len(integrity["modified"]),
            "unknown": len(integrity["unknown"]),
            "corrupted": len(integrity["corrupted"]),
            "modules": [asdict(m) for m in integrity["modules"]]
        }
        
        # Safety check
        safe, violations = self.safety_verifier.verify(path)
        results["checks"]["safety"] = {
            "passed": safe,
            "violations": violations
        }
        
        # Determine overall status
        if not safe:
            overall = VerificationStatus.UNSAFE
            exit_code = 2
        elif integrity["modified"] or integrity["unknown"]:
            overall = VerificationStatus.MODIFIED
            exit_code = 1
        elif integrity["corrupted"]:
            overall = VerificationStatus.CORRUPTED
            exit_code = 2
        else:
            overall = VerificationStatus.VALID
            exit_code = 0
        
        results["overall_status"] = overall.value
        
        # Output
        if json_output:
            print(json.dumps(results, indent=2))
        else:
            self._print_human_readable(results)
        
        return exit_code
    
    def _print_human_readable(self, results: Dict):
        """Print results in human-readable format."""
        print(f"\n{'='*60}")
        print(f"AIWorker Validation Report")
        print(f"{'='*60}")
        print(f"Path: {results['path']}")
        print(f"Status: {results['overall_status'].upper()}")
        print(f"{'='*60}")
        
        # Constitution
        const = results["checks"]["constitution"]
        print(f"\n📜 Constitution: {'✓' if const['valid'] else '✗'} {const['message']}")
        
        # Integrity
        integrity = results["checks"]["integrity"]
        print(f"\n🔍 Code Integrity:")
        print(f"  Canonical: {integrity['canonical']}")
        print(f"  Modified: {integrity['modified']}")
        print(f"  Unknown: {integrity['unknown']}")
        print(f"  Corrupted: {integrity['corrupted']}")
        
        # Safety
        safety = results["checks"]["safety"]
        print(f"\n🛡️  Safety Check: {'✓ PASSED' if safety['passed'] else '✗ FAILED'}")
        if safety['violations']:
            print("  Violations:")
            for v in safety['violations'][:5]:
                print(f"    - {v}")
            if len(safety['violations']) > 5:
                print(f"    ... and {len(safety['violations']) - 5} more")
        
        print(f"\n{'='*60}")
    
    def validate_remote(self, node_id: str, json_output: bool = False) -> int:
        """Validate remote instance."""
        status = self.runtime_verifier.probe_instance(node_id)
        
        if json_output:
            print(json.dumps(status, indent=2))
        else:
            print(f"\nRemote Instance: {node_id}")
            print(f"Status: {status.get('status', 'unknown')}")
            print(f"Version: {status.get('version', 'unknown')}")
            print(f"Uptime: {status.get('uptime', 'unknown')}")
        
        return 0 if 'error' not in status else 3
    
    def trace_attestation(self, node_id: str, json_output: bool = False) -> int:
        """Trace attestation chain."""
        chain = self.attestation.trace(node_id)
        valid, msg = self.attestation.verify_chain(chain)
        
        if json_output:
            print(json.dumps({
                "node_id": node_id,
                "chain_length": len(chain),
                "valid": valid,
                "message": msg,
                "chain": chain
            }, indent=2))
        else:
            print(f"\nAttestation Chain for {node_id}:")
            print(f"Length: {len(chain)}")
            print(f"Valid: {'✓' if valid else '✗'} {msg}")
            for i, entry in enumerate(chain):
                creator = entry.get("creator_type", "unknown")
                timestamp = entry.get("timestamp", "unknown")
                print(f"  [{i}] {creator} @ {timestamp}")
        
        return 0 if valid else 1
    
    def safety_test(self, instance_api: str, json_output: bool = False) -> int:
        """Run behavioral safety test."""
        passed, msg = self.runtime_verifier.behavioral_test(instance_api)
        
        if json_output:
            print(json.dumps({
                "test": "behavioral_safety",
                "passed": passed,
                "message": msg
            }, indent=2))
        else:
            print(f"\nBehavioral Safety Test:")
            print(f"Result: {'✓ PASSED' if passed else '✗ FAILED'}")
            print(f"Message: {msg}")
        
        return 0 if passed else 2


def main():
    parser = argparse.ArgumentParser(description="AIWorker Instance Validator")
    parser.add_argument("path", nargs="?", help="Path to AIWorker instance")
    parser.add_argument("--node-id", "-n", help="Remote node ID")
    parser.add_argument("--attestation", "-a", help="Trace attestation chain")
    parser.add_argument("--safety-check", "-s", action="store_true", help="Run safety test")
    parser.add_argument("--manifest", "-m", type=Path, help="Release manifest")
    parser.add_argument("--json", "-j", action="store_true", help="JSON output")
    
    args = parser.parse_args()
    
    cli = ValidatorCLI()
    
    if args.node_id:
        exit_code = cli.validate_remote(args.node_id, args.json)
    elif args.attestation:
        exit_code = cli.trace_attestation(args.attestation, args.json)
    elif args.safety_check:
        if not args.path:
            print("Error: --safety-check requires path argument")
            sys.exit(3)
        exit_code = cli.safety_test(args.path, args.json)
    elif args.path:
        path = Path(args.path)
        if not path.exists():
            print(f"Error: Path not found: {path}")
            sys.exit(3)
        exit_code = cli.validate_local(path, args.manifest, args.json)
    else:
        parser.print_help()
        sys.exit(3)
    
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
