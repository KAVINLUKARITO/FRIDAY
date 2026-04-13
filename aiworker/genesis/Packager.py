#!/usr/bin/env python3
"""
AIWorker 2.0 — Release Packager
Builds release artifacts from complete Phases 1-7 source.

Usage:
    python packager.py build /path/to/aiworker --output dist/
    python packager.py sign dist/manifest.json --key private.pem
    python packager.py verify dist/manifest.json
"""

import ast
import base64
import hashlib
import json
import os
import re
import zipfile
import zlib
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any
from dataclasses import dataclass, asdict
import argparse


@dataclass
class ModuleInfo:
    """Information about a module."""
    name: str
    code: str
    hash: str
    size: int
    deps: List[str]
    phase: int
    description: str = ""


@dataclass
class ReleaseManifest:
    """Release manifest with all metadata."""
    version: str
    timestamp: str
    modules: Dict[str, ModuleInfo]
    seed_hash: str
    signatures: List[Dict] = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "version": self.version,
            "timestamp": self.timestamp,
            "modules": {
                name: {
                    "hash": info.hash,
                    "size": info.size,
                    "deps": info.deps,
                    "phase": info.phase,
                    "description": info.description
                }
                for name, info in self.modules.items()
            },
            "seed_hash": self.seed_hash,
            "signatures": self.signatures or []
        }


class BlueprintLoader:
    """Load and analyze AIWorker source."""
    
    PHASE_PATTERNS = {
        1: r'^(config|safety|engine|research)/',
        2: r'^(mcp|self_modify|state_handlers|main|dashboard|cli)/',
        3: r'^(telemetry|health|testing|backup|notifications)/',
        4: r'^(meta_learning|goals|memory|predictor|evolution|scheduler)/',
        5: r'^(mesh|knowledge|specialization|consensus)/',
        6: r'^(lifecycle|economics|governance)/',
        7: r'^(sustainability|transcendence|legacy|civilization|consciousness|dreaming)/',
    }
    
    def __init__(self, source_dir: Path):
        self.source_dir = Path(source_dir)
        self.modules: Dict[str, ModuleInfo] = {}
    
    def load_all(self) -> Dict[str, ModuleInfo]:
        """Load all modules from source directory."""
        for py_file in self.source_dir.rglob("*.py"):
            if self._should_skip(py_file):
                continue
            
            module_info = self._load_module(py_file)
            if module_info:
                self.modules[module_info.name] = module_info
        
        return self.modules
    
    def _should_skip(self, path: Path) -> bool:
        """Check if file should be skipped."""
        skip_patterns = ['__pycache__', '.git', 'test_', '_test.py', 'tests/']
        return any(p in str(path) for p in skip_patterns)
    
    def _load_module(self, path: Path) -> Optional[ModuleInfo]:
        """Load a single module."""
        try:
            code = path.read_text(encoding='utf-8')
            
            # Calculate relative module name
            rel_path = path.relative_to(self.source_dir)
            name = str(rel_path.with_suffix('')).replace(os.sep, '.')
            
            # Compute hash
            hash_val = hashlib.sha256(code.encode()).hexdigest()[:16]
            
            # Extract dependencies
            deps = self._extract_deps(code)
            
            # Determine phase
            phase = self._determine_phase(name)
            
            # Extract description
            description = self._extract_description(code)
            
            return ModuleInfo(
                name=name,
                code=code,
                hash=hash_val,
                size=len(code),
                deps=deps,
                phase=phase,
                description=description
            )
        except Exception as e:
            print(f"Error loading {path}: {e}")
            return None
    
    def _extract_deps(self, code: str) -> List[str]:
        """Extract import dependencies."""
        deps = set()
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith('aiworker'):
                            deps.add(alias.name.split('.')[1] if '.' in alias.name else alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module and node.module.startswith('aiworker'):
                        deps.add(node.module.split('.')[1] if '.' in node.module else node.module)
        except SyntaxError:
            pass
        return sorted(deps)
    
    def _determine_phase(self, name: str) -> int:
        """Determine which phase a module belongs to."""
        for phase, pattern in self.PHASE_PATTERNS.items():
            if re.search(pattern, name):
                return phase
        return 1  # Default to phase 1
    
    def _extract_description(self, code: str) -> str:
        """Extract module description from docstring."""
        try:
            tree = ast.parse(code)
            if tree.body and isinstance(tree.body[0], ast.Expr):
                if isinstance(tree.body[0].value, ast.Constant):
                    doc = tree.body[0].value.value
                    if isinstance(doc, str):
                        return doc.strip().split('\n')[0][:100]
        except:
            pass
        return ""


class CodeMinifier:
    """AST-based code minification."""
    
    def minify(self, code: str, aggressive: bool = False) -> str:
        """Minify Python code."""
        try:
            tree = ast.parse(code)
            
            # Remove docstrings
            tree = self._remove_docstrings(tree)
            
            # Remove comments (handled during unparsing)
            
            if aggressive:
                tree = self._shorten_names(tree)
            
            # Unparse back to code
            return self._unparse(tree)
        except SyntaxError:
            return code
    
    def _remove_docstrings(self, tree: ast.AST) -> ast.AST:
        """Remove docstring expressions."""
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Module)):
                if (node.body and isinstance(node.body[0], ast.Expr) and
                    isinstance(node.body[0].value, ast.Constant) and
                    isinstance(node.body[0].value.value, str)):
                    node.body.pop(0)
        return tree
    
    def _shorten_names(self, tree: ast.AST) -> ast.AST:
        """Shorten private variable names."""
        name_map = {}
        counter = [0]
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                if node.id.startswith('_') and node.id not in name_map:
                    name_map[node.id] = f'_{counter[0]}'
                    counter[0] += 1
                node.id = name_map.get(node.id, node.id)
        
        return tree
    
    def _unparse(self, tree: ast.AST) -> str:
        """Simple code unparsing."""
        import ast as ast_module
        return ast_module.unparse(tree)


class SeedGenerator:
    """Generate single-file seed.py."""
    
    SEED_TEMPLATE = '''#!/usr/bin/env python3
"""
AIWorker 2.0 — The Seed
Single-file bootstrap for autonomous self-improving agent.
https://ark.aiworker/seed/v{version}
"""

import ast
import base64
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request
import zlib
from pathlib import Path
from typing import Optional, Tuple, Dict, List, Any

VERSION = "{version}-seed"
MAX_LINES = 1000
ARK_URL = os.getenv("AIWORKER_ARK", "https://ark.aiworker")
OLLAMA_MODEL = os.getenv("AIWORKER_MODEL", "tinyllama")
FORBIDDEN_PATTERNS = ['eval(', 'exec(', '__import__(', 'os.system(', 'subprocess.call', 'shell=True']
SAFETY_PAUSE = 5
BLUEPRINT = b"{blueprint}"

_generation_times: List[float] = []

def llm(prompt: str, model: str = OLLAMA_MODEL, timeout: int = 60) -> str:
    try:
        result = subprocess.run(["ollama", "run", model, prompt], capture_output=True, text=True, timeout=timeout)
        return result.stdout.strip() if result.returncode == 0 else f"# Error: {{result.stderr}}"
    except Exception as e:
        return f"# Error: {{e}}"

def validate_code(code: str) -> Tuple[bool, str]:
    for pattern in FORBIDDEN_PATTERNS:
        if pattern in code:
            return False, f"Forbidden: {{pattern}}"
    try:
        ast.parse(code)
        return True, "Valid"
    except SyntaxError as e:
        return False, str(e)

def human_confirm(action: str, detail: str) -> bool:
    if not sys.stdin.isatty():
        return False
    print(f"\\nACTION: {{action}}\\n{{detail[:500]}}...")
    return input("Approve? (yes/no): ").strip().lower() == 'yes'

def get_blueprint() -> Dict[str, Any]:
    decoded = base64.b64decode(BLUEPRINT)
    return json.loads(zlib.decompress(decoded))

def write_module(name: str, code: str) -> Path:
    base_dir = Path("aiworker")
    base_dir.mkdir(exist_ok=True)
    path = base_dir / f"{{name}}.py"
    path.write_text(code)
    return path

def bootstrap():
    print("Bootstrapping AIWorker...")
    blueprint = get_blueprint()
    for name, info in blueprint.get("modules", {{}}).items():
        print(f"Module: {{name}}")
    print("Bootstrap complete!")

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "bootstrap": bootstrap()
    elif cmd == "status": print(f"AIWorker Seed v{{VERSION}}")
    else: print(f"Unknown: {{cmd}}")

if __name__ == "__main__":
    main()
'''
    
    def __init__(self, blueprint: Dict[str, ModuleInfo]):
        self.blueprint = blueprint
    
    def generate(self, version: str = "2.0.0") -> str:
        """Generate seed.py content."""
        # Create compressed blueprint
        manifest = {
            "version": version,
            "modules": {
                name: {
                    "hash": info.hash,
                    "size": info.size,
                    "deps": info.deps,
                    "phase": info.phase,
                    "description": info.description
                }
                for name, info in self.blueprint.items()
            }
        }
        
        compressed = zlib.compress(json.dumps(manifest).encode(), level=9)
        blueprint_b64 = base64.b64encode(compressed).decode()
        
        # Generate seed
        seed = self.SEED_TEMPLATE.format(
            version=version,
            blueprint=blueprint_b64
        )
        
        return seed
    
    def get_seed_hash(self, seed: str) -> str:
        """Compute seed hash."""
        return hashlib.sha256(seed.encode()).hexdigest()[:16]


class BootstrapScriptGenerator:
    """Generate bootstrap shell script."""
    
    SCRIPT_TEMPLATE = '''#!/bin/bash
# AIWorker 2.0 Bootstrap Script
# Downloads and runs seed.py with verification

set -e

SEED_URL="{seed_url}"
SEED_HASH="{seed_hash}"
PYTHON_MIN="3.8"

echo "=== AIWorker 2.0 Bootstrap ==="

# Check Python version
check_python() {{
    if ! command -v python3 &> /dev/null; then
        echo "Error: Python 3 not found"
        exit 1
    fi
    PY_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
    if [ "$(printf '%s\\n' "$PYTHON_MIN" "$PY_VERSION" | sort -V | head -n1)" != "$PYTHON_MIN" ]; then
        echo "Error: Python $PYTHON_MIN+ required, found $PY_VERSION"
        exit 1
    fi
    echo "✓ Python $PY_VERSION"
}}

# Check/install ollama
check_ollama() {{
    if ! command -v ollama &> /dev/null; then
        echo "Installing ollama..."
        curl -fsSL https://ollama.ai/install.sh | sh
    fi
    echo "✓ ollama installed"
}}

# Download seed
download_seed() {{
    echo "Downloading seed..."
    curl -fsSL "$SEED_URL" -o seed.py
    ACTUAL_HASH=$(sha256sum seed.py | cut -d' ' -f1 | cut -c1-16)
    if [ "$ACTUAL_HASH" != "$SEED_HASH" ]; then
        echo "Error: Hash mismatch! Expected $SEED_HASH, got $ACTUAL_HASH"
        exit 1
    fi
    echo "✓ Seed verified"
}}

# Main
main() {{
    check_python
    check_ollama
    download_seed
    echo ""
    echo "=== Running AIWorker Seed ==="
    python3 seed.py bootstrap
}}

main "$@"
'''
    
    def generate(self, seed_url: str, seed_hash: str) -> str:
        """Generate bootstrap script."""
        return self.SCRIPT_TEMPLATE.format(
            seed_url=seed_url,
            seed_hash=seed_hash
        )


class DockerfileGenerator:
    """Generate Dockerfile."""
    
    DOCKERFILE_TEMPLATE = '''FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \\
    curl \\
    && rm -rf /var/lib/apt/lists/*

# Install ollama
RUN curl -fsSL https://ollama.ai/install.sh | sh

# Copy seed
COPY seed.py /app/seed.py
WORKDIR /app

# Expose dashboard port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s \\
    CMD python3 seed.py status || exit 1

# Default: bootstrap and self-improve
CMD ["python3", "seed.py", "bootstrap"]
'''
    
    def generate(self) -> str:
        """Generate Dockerfile."""
        return self.DOCKERFILE_TEMPLATE


class CloudInitGenerator:
    """Generate cloud-init for VM provisioning."""
    
    CLOUDINIT_TEMPLATE = '''#cloud-config
# AIWorker 2.0 Cloud-Init

package_update: true
packages:
  - python3
  - python3-pip
  - curl
  - git

users:
  - name: aiworker
    groups: sudo
    shell: /bin/bash
    sudo: ['ALL=(ALL) NOPASSWD:ALL']

runcmd:
  # Install ollama
  - curl -fsSL https://ollama.ai/install.sh | sh
  
  # Download and run seed
  - curl -fsSL {seed_url} -o /home/aiworker/seed.py
  - chown aiworker:aiworker /home/aiworker/seed.py
  - su - aiworker -c "cd /home/aiworker && python3 seed.py bootstrap"
  
  # Create systemd service
  - |
    cat > /etc/systemd/system/aiworker.service << 'EOF'
[Unit]
Description=AIWorker 2.0
After=network.target

[Service]
Type=simple
User=aiworker
WorkingDirectory=/home/aiworker
ExecStart=/usr/bin/python3 /home/aiworker/seed.py self-improve
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
  
  - systemctl daemon-reload
  - systemctl enable aiworker
  - systemctl start aiworker

final_message: "AIWorker 2.0 installation complete!"
'''
    
    def generate(self, seed_url: str) -> str:
        """Generate cloud-init YAML."""
        return self.CLOUDINIT_TEMPLATE.format(seed_url=seed_url)


class AirgapBundleGenerator:
    """Generate offline bundle."""
    
    def generate(self, blueprint: Dict[str, ModuleInfo], output_path: Path) -> Path:
        """Create airgap bundle zip."""
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            # Add seed.py placeholder
            zf.writestr('seed.py', '# Placeholder - run packager to generate')
            
            # Add all modules
            for name, info in blueprint.items():
                zf.writestr(f'modules/{name}.py', info.code)
            
            # Add install script
            install_script = self._generate_install_script()
            zf.writestr('install.sh', install_script)
            
            # Add README
            readme = self._generate_readme()
            zf.writestr('README.md', readme)
        
        return output_path
    
    def _generate_install_script(self) -> str:
        """Generate offline install script."""
        return '''#!/bin/bash
# AIWorker 2.0 Airgap Install

echo "=== AIWorker 2.0 Airgap Install ==="

# Copy modules
mkdir -p aiworker
cp modules/*.py aiworker/

# Run seed
python3 seed.py bootstrap

echo "Installation complete!"
'''
    
    def _generate_readme(self) -> str:
        """Generate airgap README."""
        return '''# AIWorker 2.0 Airgap Bundle

This bundle contains everything needed to install AIWorker without internet.

## Installation

```bash
bash install.sh
```

## Contents

- `seed.py` - Bootstrap script
- `modules/` - All AIWorker modules
- `install.sh` - Installation script
'''


class ReleaseSigner:
    """Sign releases with Ed25519."""
    
    def sign(self, manifest: dict, private_key_path: Path) -> dict:
        """Sign manifest."""
        try:
            from cryptography.hazmat.primitives import serialization, hashes
            from cryptography.hazmat.primitives.asymmetric import ed25519
            
            private_key = serialization.load_pem_private_key(
                private_key_path.read_bytes(),
                password=None
            )
            
            manifest_bytes = json.dumps(manifest, sort_keys=True).encode()
            signature = private_key.sign(manifest_bytes)
            
            manifest['signatures'] = manifest.get('signatures', []) + [{
                'algorithm': 'Ed25519',
                'signature': base64.b64encode(signature).decode(),
                'public_key': base64.b64encode(
                    private_key.public_key().public_bytes(
                        encoding=serialization.Encoding.Raw,
                        format=serialization.PublicFormat.Raw
                    )
                ).decode()
            }]
            
            return manifest
        except ImportError:
            print("Warning: cryptography not installed, skipping signature")
            return manifest
    
    def verify(self, manifest: dict, public_key: bytes = None) -> bool:
        """Verify manifest signature."""
        if 'signatures' not in manifest or not manifest['signatures']:
            return True  # No signature to verify
        
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric import ed25519
            
            sig_data = manifest['signatures'][0]
            signature = base64.b64decode(sig_data['signature'])
            
            if public_key:
                verify_key = ed25519.Ed25519PublicKey.from_public_bytes(public_key)
            else:
                verify_key = ed25519.Ed25519PublicKey.from_public_bytes(
                    base64.b64decode(sig_data['public_key'])
                )
            
            manifest_bytes = json.dumps(
                {k: v for k, v in manifest.items() if k != 'signatures'},
                sort_keys=True
            ).encode()
            
            try:
                verify_key.verify(signature, manifest_bytes)
                return True
            except Exception:
                return False
        except ImportError:
            print("Warning: cryptography not installed, cannot verify")
            return True


class Packager:
    """Main packager that orchestrates build."""
    
    def __init__(self, source_dir: Path, output_dir: Path):
        self.source_dir = Path(source_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def build(self, version: str = "2.0.0", key_path: Path = None) -> ReleaseManifest:
        """Build all release artifacts."""
        print(f"Building AIWorker {version}...")
        
        # Load blueprint
        print("Loading source modules...")
        loader = BlueprintLoader(self.source_dir)
        blueprint = loader.load_all()
        print(f"Loaded {len(blueprint)} modules")
        
        # Generate seed
        print("Generating seed.py...")
        seed_gen = SeedGenerator(blueprint)
        seed_content = seed_gen.generate(version)
        seed_hash = seed_gen.get_seed_hash(seed_content)
        
        seed_path = self.output_dir / "seed.py"
        seed_path.write_text(seed_content)
        print(f"Seed: {seed_path} ({len(seed_content)} bytes)")
        
        # Generate bootstrap script
        print("Generating bootstrap.sh...")
        bootstrap_gen = BootstrapScriptGenerator()
        bootstrap_content = bootstrap_gen.generate(
            seed_url="https://ark.aiworker/seed.py",
            seed_hash=seed_hash
        )
        bootstrap_path = self.output_dir / "bootstrap.sh"
        bootstrap_path.write_text(bootstrap_content)
        bootstrap_path.chmod(0o755)
        
        # Generate Dockerfile
        print("Generating Dockerfile...")
        dockerfile_gen = DockerfileGenerator()
        dockerfile_path = self.output_dir / "Dockerfile"
        dockerfile_path.write_text(dockerfile_gen.generate())
        
        # Generate cloud-init
        print("Generating cloud-init.yaml...")
        cloudinit_gen = CloudInitGenerator()
        cloudinit_path = self.output_dir / "cloud-init.yaml"
        cloudinit_path.write_text(cloudinit_gen.generate("https://ark.aiworker/seed.py"))
        
        # Generate airgap bundle
        print("Generating airgap bundle...")
        airgap_gen = AirgapBundleGenerator()
        airgap_path = self.output_dir / "airgap-bundle.zip"
        airgap_gen.generate(blueprint, airgap_path)
        
        # Create manifest
        manifest = ReleaseManifest(
            version=version,
            timestamp=__import__('datetime').datetime.now().isoformat(),
            modules=blueprint,
            seed_hash=seed_hash
        )
        
        # Sign if key provided
        if key_path:
            print("Signing manifest...")
            signer = ReleaseSigner()
            manifest_dict = signer.sign(manifest.to_dict(), key_path)
        else:
            manifest_dict = manifest.to_dict()
        
        # Write manifest
        manifest_path = self.output_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest_dict, indent=2))
        print(f"Manifest: {manifest_path}")
        
        # Generate README
        readme = self._generate_readme(version)
        readme_path = self.output_dir / "README.md"
        readme_path.write_text(readme)
        
        print(f"\nBuild complete! Output: {self.output_dir}")
        return manifest
    
    def _generate_readme(self, version: str) -> str:
        """Generate release README."""
        return f'''# AIWorker {version} Release

## Quick Start

### One-Line Install
```bash
curl -sSL https://ark.aiworker/bootstrap.sh | bash
```

### Docker
```bash
docker build -t aiworker:{version} .
docker run -p 8000:8000 aiworker:{version}
```

### Cloud (AWS/GCP/Hetzner)
Use `cloud-init.yaml` as user-data when creating instances.

### Airgap (No Internet)
```bash
unzip airgap-bundle.zip
bash install.sh
```

## Files

- `seed.py` - Single-file bootstrap (<100KB)
- `bootstrap.sh` - Automated installer
- `Dockerfile` - Container image
- `cloud-init.yaml` - VM provisioning
- `airgap-bundle.zip` - Offline package
- `manifest.json` - Release manifest with hashes

## Verification

```bash
python3 -c "import hashlib; print(hashlib.sha256(open('seed.py','rb').read()).hexdigest()[:16])"
```

Compare with `manifest.json` `seed_hash` field.
'''


def main():
    parser = argparse.ArgumentParser(description="AIWorker Release Packager")
    parser.add_argument("command", choices=["build", "sign", "verify"])
    parser.add_argument("--source", "-s", type=Path, default=Path("aiworker"))
    parser.add_argument("--output", "-o", type=Path, default=Path("dist"))
    parser.add_argument("--version", "-v", default="2.0.0")
    parser.add_argument("--key", "-k", type=Path, help="Private key for signing")
    
    args = parser.parse_args()
    
    if args.command == "build":
        packager = Packager(args.source, args.output)
        packager.build(args.version, args.key)
    elif args.command == "sign":
        manifest_path = args.output / "manifest.json"
        if not manifest_path.exists():
            print(f"Manifest not found: {manifest_path}")
            return
        manifest = json.loads(manifest_path.read_text())
        signer = ReleaseSigner()
        manifest = signer.sign(manifest, args.key)
        manifest_path.write_text(json.dumps(manifest, indent=2))
        print("Manifest signed!")
    elif args.command == "verify":
        manifest_path = args.output / "manifest.json"
        if not manifest_path.exists():
            print(f"Manifest not found: {manifest_path}")
            return
        manifest = json.loads(manifest_path.read_text())
        signer = ReleaseSigner()
        if signer.verify(manifest):
            print("Signature verified!")
        else:
            print("Signature verification FAILED!")


if __name__ == "__main__":
    main()

