#!/usr/bin/env python3
"""
AIWorker 2.0 — Platform Adapter
Platform abstraction for any hardware or environment.

Usage:
    python adapter.py detect                    # Detect environment
    python adapter.py configure --profile vps   # Configure for profile
    python adapter.py migrate --export state.aiw   # Export state
    python adapter.py migrate --import state.aiw   # Import state
"""

import argparse
import json
import os
import platform
import re
import subprocess
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple


@dataclass
class SystemResources:
    """System resource information."""
    total_ram_mb: int
    available_ram_mb: int
    total_disk_mb: int
    available_disk_mb: int
    cpu_count: int
    has_gpu: bool
    gpu_type: Optional[str]
    is_container: bool
    has_network: bool
    platform: str


@dataclass
class AdapterConfig:
    """Configuration for AIWorker."""
    ollama_memory_gb: float
    max_loaded_models: int
    enable_mesh: bool
    enable_self_modify: bool
    model_default: str
    max_iterations_per_day: int
    checkpoint_interval: int
    backup_enabled: bool
    log_level: str
    max_concurrent_tasks: int


class AdapterProfile(ABC):
    """Base class for platform-specific configuration."""
    
    name: str = "base"
    min_ram_mb: int = 4096
    min_disk_mb: int = 10000
    recommended_model: str = "tinyllama"
    capabilities: List[str] = ["core"]
    
    @abstractmethod
    def configure(self, config: AdapterConfig) -> AdapterConfig:
        """Adjust configuration for platform."""
        pass
    
    def check_compatibility(self, resources: SystemResources) -> Tuple[bool, str]:
        """Check if platform meets minimum requirements."""
        if resources.total_ram_mb < self.min_ram_mb:
            return False, f"Insufficient RAM: {resources.total_ram_mb}MB < {self.min_ram_mb}MB"
        if resources.available_disk_mb < self.min_disk_mb:
            return False, f"Insufficient disk: {resources.available_disk_mb}MB < {self.min_disk_mb}MB"
        return True, "Compatible"


class VPS32GB(AdapterProfile):
    """Standard VPS deployment (Phases 1-7 full)."""
    
    name = "vps-32gb"
    min_ram_mb = 32768
    min_disk_mb = 100000
    recommended_model = "deepseek-coder:6.7b"
    capabilities = ["all"]
    
    def configure(self, config: AdapterConfig) -> AdapterConfig:
        config.ollama_memory_gb = 20.0
        config.max_loaded_models = 2
        config.enable_mesh = True
        config.enable_self_modify = True
        config.model_default = "deepseek-coder:6.7b"
        config.max_iterations_per_day = 50
        config.checkpoint_interval = 300
        config.backup_enabled = True
        config.max_concurrent_tasks = 8
        return config


class VPS16GB(AdapterProfile):
    """Medium VPS deployment (Phases 1-6)."""
    
    name = "vps-16gb"
    min_ram_mb = 16384
    min_disk_mb = 50000
    recommended_model = "deepseek-coder:1.3b"
    capabilities = ["core", "integration", "production", "intelligence", "ecosystem"]
    
    def configure(self, config: AdapterConfig) -> AdapterConfig:
        config.ollama_memory_gb = 10.0
        config.max_loaded_models = 1
        config.enable_mesh = True
        config.enable_self_modify = True
        config.model_default = "deepseek-coder:1.3b"
        config.max_iterations_per_day = 20
        config.checkpoint_interval = 300
        config.backup_enabled = True
        config.max_concurrent_tasks = 4
        return config


class Laptop16GB(AdapterProfile):
    """Development laptop (Phases 1-5, limited mesh)."""
    
    name = "laptop-16gb"
    min_ram_mb = 16384
    min_disk_mb = 20000
    recommended_model = "codellama:7b"
    capabilities = ["core", "integration", "production", "intelligence"]
    
    def configure(self, config: AdapterConfig) -> AdapterConfig:
        config.ollama_memory_gb = 8.0
        config.max_loaded_models = 1
        config.enable_mesh = False  # No mesh on laptop
        config.enable_self_modify = True
        config.model_default = "codellama:7b"
        config.max_iterations_per_day = 5
        config.checkpoint_interval = 600
        config.backup_enabled = True
        config.max_concurrent_tasks = 2
        config.log_level = "DEBUG"
        return config


class Embedded4GB(AdapterProfile):
    """Raspberry Pi 4, edge devices (Phase 1-3 only, minimal)."""
    
    name = "embedded-4gb"
    min_ram_mb = 4096
    min_disk_mb = 8000
    recommended_model = "tinyllama"
    capabilities = ["core"]
    
    def configure(self, config: AdapterConfig) -> AdapterConfig:
        config.ollama_memory_gb = 2.0
        config.max_loaded_models = 1
        config.enable_mesh = False
        config.enable_self_modify = False  # Safety: manual only
        config.model_default = "tinyllama"
        config.max_iterations_per_day = 1
        config.checkpoint_interval = 1800
        config.backup_enabled = False
        config.max_concurrent_tasks = 1
        config.log_level = "WARNING"
        return config


class Embedded8GB(AdapterProfile):
    """Raspberry Pi 5, better edge devices (Phases 1-4)."""
    
    name = "embedded-8gb"
    min_ram_mb = 8192
    min_disk_mb = 16000
    recommended_model = "phi3:mini"
    capabilities = ["core", "integration", "production"]
    
    def configure(self, config: AdapterConfig) -> AdapterConfig:
        config.ollama_memory_gb = 4.0
        config.max_loaded_models = 1
        config.enable_mesh = False
        config.enable_self_modify = True
        config.model_default = "phi3:mini"
        config.max_iterations_per_day = 3
        config.checkpoint_interval = 900
        config.backup_enabled = True
        config.max_concurrent_tasks = 2
        return config


class Airgapped(AdapterProfile):
    """No network access, USB-only updates."""
    
    name = "airgapped"
    min_ram_mb = 8192
    min_disk_mb = 50000
    recommended_model = "deepseek-coder:1.3b"
    capabilities = ["core", "integration", "production"]
    
    def configure(self, config: AdapterConfig) -> AdapterConfig:
        config.ollama_memory_gb = 6.0
        config.max_loaded_models = 1
        config.enable_mesh = False
        config.enable_self_modify = True
        config.model_default = "deepseek-coder:1.3b"
        config.max_iterations_per_day = 10
        config.backup_enabled = True
        return config


class BrowserWASM(AdapterProfile):
    """Experimental: WebAssembly in browser."""
    
    name = "browser-wasm"
    min_ram_mb = 2048
    min_disk_mb = 100
    recommended_model = "webllm"
    capabilities = ["core"]
    
    def configure(self, config: AdapterConfig) -> AdapterConfig:
        config.ollama_memory_gb = 1.0
        config.max_loaded_models = 1
        config.enable_mesh = False
        config.enable_self_modify = False
        config.model_default = "webllm"
        config.max_iterations_per_day = 0  # Manual only
        config.checkpoint_interval = 0
        config.backup_enabled = False
        config.max_concurrent_tasks = 1
        return config


# Registry of all profiles
PROFILES: Dict[str, AdapterProfile] = {
    "vps-32gb": VPS32GB(),
    "vps-16gb": VPS16GB(),
    "laptop-16gb": Laptop16GB(),
    "embedded-4gb": Embedded4GB(),
    "embedded-8gb": Embedded8GB(),
    "airgapped": Airgapped(),
    "browser-wasm": BrowserWASM(),
}


class ResourceDetector:
    """Detect system resources."""
    
    def detect(self) -> SystemResources:
        """Detect all system resources."""
        return SystemResources(
            total_ram_mb=self._get_total_ram(),
            available_ram_mb=self._get_available_ram(),
            total_disk_mb=self._get_total_disk(),
            available_disk_mb=self._get_available_disk(),
            cpu_count=self._get_cpu_count(),
            has_gpu=self._has_gpu(),
            gpu_type=self._get_gpu_type(),
            is_container=self._is_container(),
            has_network=self._has_network(),
            platform=platform.platform()
        )
    
    def _get_total_ram(self) -> int:
        """Get total RAM in MB."""
        try:
            # Try /proc/meminfo on Linux
            if Path("/proc/meminfo").exists():
                meminfo = Path("/proc/meminfo").read_text()
                match = re.search(r'MemTotal:\s+(\d+)\s+kB', meminfo)
                if match:
                    return int(match.group(1)) // 1024
        except:
            pass
        
        # Fallback to sys.maxsize heuristic
        import sys
        return min(32768, max(4096, (sys.maxsize > 2**32) * 16384))
    
    def _get_available_ram(self) -> int:
        """Get available RAM in MB."""
        try:
            if Path("/proc/meminfo").exists():
                meminfo = Path("/proc/meminfo").read_text()
                match = re.search(r'MemAvailable:\s+(\d+)\s+kB', meminfo)
                if match:
                    return int(match.group(1)) // 1024
                # Fallback to MemFree
                match = re.search(r'MemFree:\s+(\d+)\s+kB', meminfo)
                if match:
                    return int(match.group(1)) // 1024
        except:
            pass
        return self._get_total_ram() // 2
    
    def _get_total_disk(self) -> int:
        """Get total disk in MB."""
        try:
            stat = os.statvfs('.')
            return (stat.f_blocks * stat.f_frsize) // (1024 * 1024)
        except:
            return 100000
    
    def _get_available_disk(self) -> int:
        """Get available disk in MB."""
        try:
            stat = os.statvfs('.')
            return (stat.f_bavail * stat.f_frsize) // (1024 * 1024)
        except:
            return 50000
    
    def _get_cpu_count(self) -> int:
        """Get CPU count."""
        return os.cpu_count() or 2
    
    def _has_gpu(self) -> bool:
        """Check if GPU is available."""
        # Check for NVIDIA
        try:
            subprocess.run(['nvidia-smi'], capture_output=True, check=True)
            return True
        except:
            pass
        
        # Check for AMD
        try:
            subprocess.run(['rocm-smi'], capture_output=True, check=True)
            return True
        except:
            pass
        
        # Check for Apple Metal
        if platform.system() == "Darwin":
            try:
                result = subprocess.run(['system_profiler', 'SPDisplaysDataType'],
                                      capture_output=True, text=True)
                return "Metal" in result.stdout
            except:
                pass
        
        return False
    
    def _get_gpu_type(self) -> Optional[str]:
        """Get GPU type if available."""
        try:
            result = subprocess.run(['nvidia-smi', '--query-gpu=name', '--format=csv,noheader'],
                                  capture_output=True, text=True)
            if result.returncode == 0:
                return f"NVIDIA {result.stdout.strip()}"
        except:
            pass
        
        if platform.system() == "Darwin":
            return "Apple Metal"
        
        return None
    
    def _is_container(self) -> bool:
        """Check if running in container."""
        # Check for .dockerenv
        if Path("/.dockerenv").exists():
            return True
        
        # Check cgroup
        try:
            cgroup = Path("/proc/self/cgroup").read_text()
            return "docker" in cgroup or "containerd" in cgroup
        except:
            pass
        
        return False
    
    def _has_network(self) -> bool:
        """Check if network is available."""
        try:
            import socket
            socket.create_connection(("8.8.8.8", 53), timeout=3)
            return True
        except:
            pass
        
        # Try alternative
        try:
            import urllib.request
            urllib.request.urlopen('http://1.1.1.1', timeout=3)
            return True
        except:
            pass
        
        return False


class ProfileSelector:
    """Select best profile for environment."""
    
    def __init__(self):
        self.detector = ResourceDetector()
    
    def select(self, resources: SystemResources = None) -> Tuple[AdapterProfile, str]:
        """Select best matching profile."""
        if resources is None:
            resources = self.detector.detect()
        
        # Check for airgapped
        if not resources.has_network:
            return Airgapped(), "No network detected"
        
        # Check for container
        if resources.is_container:
            # Select based on RAM
            if resources.total_ram_mb >= 32000:
                return VPS32GB(), "Container with 32GB+ RAM"
            elif resources.total_ram_mb >= 16000:
                return VPS16GB(), "Container with 16GB RAM"
            else:
                return Embedded8GB(), "Container with limited RAM"
        
        # Check for embedded/edge
        if resources.total_ram_mb < 6000:
            return Embedded4GB(), f"Limited RAM: {resources.total_ram_mb}MB"
        elif resources.total_ram_mb < 12000:
            return Embedded8GB(), f"Moderate RAM: {resources.total_ram_mb}MB"
        
        # Check for laptop
        if platform.system() in ["Darwin", "Windows"] or self._is_laptop():
            return Laptop16GB(), "Laptop environment detected"
        
        # Default to VPS profiles
        if resources.total_ram_mb >= 32000:
            return VPS32GB(), f"Server with {resources.total_ram_mb}MB RAM"
        else:
            return VPS16GB(), f"Server with {resources.total_ram_mb}MB RAM"
    
    def _is_laptop(self) -> bool:
        """Heuristic to detect laptop."""
        # Check for battery
        if Path("/sys/class/power_supply/BAT0").exists():
            return True
        
        # Check for common laptop indicators
        try:
            result = subprocess.run(['dmidecode', '-s', 'chassis-type'],
                                  capture_output=True, text=True)
            if "Notebook" in result.stdout or "Laptop" in result.stdout:
                return True
        except:
            pass
        
        return False


class StateMigration:
    """Handle state migration between platforms."""
    
    def __init__(self, config_path: Path = Path("aiworker.json")):
        self.config_path = config_path
    
    def export_state(self, output_path: Path, password: str = None) -> Path:
        """Serialize state for migration."""
        state = {
            "version": "2.0.0",
            "timestamp": __import__('datetime').datetime.now().isoformat(),
            "config": self._load_config(),
            "checkpoint": self._load_checkpoint(),
            "skills": self._load_skills(),
        }
        
        # Serialize
        data = json.dumps(state, indent=2).encode()
        
        # Compress
        import zlib
        compressed = zlib.compress(data, level=9)
        
        # Encrypt if password provided
        if password:
            # Simple XOR for demo - use proper encryption in production
            key = hashlib.sha256(password.encode()).digest()
            encrypted = bytes(b ^ key[i % len(key)] for i, b in enumerate(compressed))
        else:
            encrypted = compressed
        
        # Write with header
        header = b'AIWSTATE\x00'
        output_path.write_bytes(header + encrypted)
        
        return output_path
    
    def import_state(self, input_path: Path, target_profile: AdapterProfile,
                     password: str = None) -> bool:
        """Restore state on new platform."""
        data = input_path.read_bytes()
        
        # Check header
        if not data.startswith(b'AIWSTATE\x00'):
            raise ValueError("Invalid state file format")
        
        encrypted = data[9:]
        
        # Decrypt if password provided
        if password:
            key = hashlib.sha256(password.encode()).digest()
            compressed = bytes(b ^ key[i % len(key)] for i, b in enumerate(encrypted))
        else:
            compressed = encrypted
        
        # Decompress
        import zlib
        data = zlib.decompress(compressed)
        state = json.loads(data.decode())
        
        # Adapt configuration
        config = state.get("config", {})
        adapted = self._adapt_config(config, target_profile)
        
        # Write adapted config
        self._save_config(adapted)
        
        # Restore checkpoint
        if state.get("checkpoint"):
            self._save_checkpoint(state["checkpoint"])
        
        # Restore skills
        if state.get("skills"):
            self._save_skills(state["skills"])
        
        return True
    
    def _load_config(self) -> dict:
        """Load current config."""
        if self.config_path.exists():
            return json.loads(self.config_path.read_text())
        return {}
    
    def _save_config(self, config: dict) -> None:
        """Save config."""
        self.config_path.write_text(json.dumps(config, indent=2))
    
    def _load_checkpoint(self) -> Optional[dict]:
        """Load checkpoint data."""
        checkpoint_path = Path("checkpoint.json")
        if checkpoint_path.exists():
            return json.loads(checkpoint_path.read_text())
        return None
    
    def _save_checkpoint(self, checkpoint: dict) -> None:
        """Save checkpoint."""
        Path("checkpoint.json").write_text(json.dumps(checkpoint, indent=2))
    
    def _load_skills(self) -> dict:
        """Load skills data."""
        skills_path = Path("skills.json")
        if skills_path.exists():
            return json.loads(skills_path.read_text())
        return {}
    
    def _save_skills(self, skills: dict) -> None:
        """Save skills."""
        Path("skills.json").write_text(json.dumps(skills, indent=2))
    
    def _adapt_config(self, config: dict, profile: AdapterProfile) -> dict:
        """Adapt configuration to target profile."""
        base_config = AdapterConfig(
            ollama_memory_gb=config.get("ollama_memory_gb", 4.0),
            max_loaded_models=config.get("max_loaded_models", 1),
            enable_mesh=config.get("enable_mesh", True),
            enable_self_modify=config.get("enable_self_modify", True),
            model_default=config.get("model_default", "tinyllama"),
            max_iterations_per_day=config.get("max_iterations_per_day", 10),
            checkpoint_interval=config.get("checkpoint_interval", 300),
            backup_enabled=config.get("backup_enabled", True),
            log_level=config.get("log_level", "INFO"),
            max_concurrent_tasks=config.get("max_concurrent_tasks", 2)
        )
        
        adapted = profile.configure(base_config)
        return {
            "ollama_memory_gb": adapted.ollama_memory_gb,
            "max_loaded_models": adapted.max_loaded_models,
            "enable_mesh": adapted.enable_mesh,
            "enable_self_modify": adapted.enable_self_modify,
            "model_default": adapted.model_default,
            "max_iterations_per_day": adapted.max_iterations_per_day,
            "checkpoint_interval": adapted.checkpoint_interval,
            "backup_enabled": adapted.backup_enabled,
            "log_level": adapted.log_level,
            "max_concurrent_tasks": adapted.max_concurrent_tasks,
            "profile": profile.name
        }


class AdapterCLI:
    """Command-line interface for adapter."""
    
    def __init__(self):
        self.detector = ResourceDetector()
        self.selector = ProfileSelector()
        self.migration = StateMigration()
    
    def detect(self) -> None:
        """Detect and display environment."""
        resources = self.detector.detect()
        profile, reason = self.selector.select(resources)
        
        print(f"\n{'='*50}")
        print("Environment Detection")
        print(f"{'='*50}")
        print(f"Platform: {resources.platform}")
        print(f"RAM: {resources.available_ram_mb}MB / {resources.total_ram_mb}MB")
        print(f"Disk: {resources.available_disk_mb}MB / {resources.total_disk_mb}MB")
        print(f"CPUs: {resources.cpu_count}")
        print(f"GPU: {resources.gpu_type or 'None'}")
        print(f"Container: {'Yes' if resources.is_container else 'No'}")
        print(f"Network: {'Yes' if resources.has_network else 'No'}")
        print(f"{'='*50}")
        print(f"Recommended Profile: {profile.name}")
        print(f"Reason: {reason}")
        print(f"Capabilities: {', '.join(profile.capabilities)}")
        print(f"{'='*50}\n")
    
    def configure(self, profile_name: str, output: Path = None) -> None:
        """Configure for specific profile."""
        if profile_name not in PROFILES:
            print(f"Unknown profile: {profile_name}")
            print(f"Available: {', '.join(PROFILES.keys())}")
            return
        
        profile = PROFILES[profile_name]
        resources = self.detector.detect()
        
        compatible, reason = profile.check_compatibility(resources)
        if not compatible:
            print(f"Warning: {reason}")
            response = input("Continue anyway? (yes/no): ").strip().lower()
            if response != 'yes':
                return
        
        # Create config
        base_config = AdapterConfig(
            ollama_memory_gb=4.0,
            max_loaded_models=1,
            enable_mesh=True,
            enable_self_modify=True,
            model_default="tinyllama",
            max_iterations_per_day=10,
            checkpoint_interval=300,
            backup_enabled=True,
            log_level="INFO",
            max_concurrent_tasks=2
        )
        
        adapted = profile.configure(base_config)
        config_dict = {
            "ollama_memory_gb": adapted.ollama_memory_gb,
            "max_loaded_models": adapted.max_loaded_models,
            "enable_mesh": adapted.enable_mesh,
            "enable_self_modify": adapted.enable_self_modify,
            "model_default": adapted.model_default,
            "max_iterations_per_day": adapted.max_iterations_per_day,
            "checkpoint_interval": adapted.checkpoint_interval,
            "backup_enabled": adapted.backup_enabled,
            "log_level": adapted.log_level,
            "max_concurrent_tasks": adapted.max_concurrent_tasks,
            "profile": profile_name
        }
        
        output = output or Path("aiworker.json")
        output.write_text(json.dumps(config_dict, indent=2))
        print(f"Configuration saved to {output}")
    
    def list_profiles(self) -> None:
        """List all available profiles."""
        print(f"\n{'='*70}")
        print("Available Profiles")
        print(f"{'='*70}")
        
        for name, profile in PROFILES.items():
            print(f"\n{name}:")
            print(f"  Min RAM: {profile.min_ram_mb}MB")
            print(f"  Min Disk: {profile.min_disk_mb}MB")
            print(f"  Model: {profile.recommended_model}")
            print(f"  Capabilities: {', '.join(profile.capabilities)}")
        
        print(f"{'='*70}\n")
    
    def export_state(self, output: Path, password: str = None) -> None:
        """Export state for migration."""
        path = self.migration.export_state(output, password)
        print(f"State exported to {path}")
    
    def import_state(self, input_path: Path, profile_name: str,
                     password: str = None) -> None:
        """Import state from migration."""
        if profile_name not in PROFILES:
            print(f"Unknown profile: {profile_name}")
            return
        
        profile = PROFILES[profile_name]
        self.migration.import_state(input_path, profile, password)
        print(f"State imported and adapted for {profile_name}")


def main():
    parser = argparse.ArgumentParser(description="AIWorker Platform Adapter")
    subparsers = parser.add_subparsers(dest="command")
    
    # Detect
    detect_parser = subparsers.add_parser("detect", help="Detect environment")
    
    # Configure
    config_parser = subparsers.add_parser("configure", help="Configure for profile")
    config_parser.add_argument("--profile", "-p", required=True, help="Profile name")
    config_parser.add_argument("--output", "-o", type=Path, help="Output file")
    
    # List profiles
    list_parser = subparsers.add_parser("list", help="List profiles")
    
    # Export
    export_parser = subparsers.add_parser("export", help="Export state")
    export_parser.add_argument("output", type=Path, help="Output file")
    export_parser.add_argument("--password", help="Encryption password")
    
    # Import
    import_parser = subparsers.add_parser("import", help="Import state")
    import_parser.add_argument("input", type=Path, help="Input file")
    import_parser.add_argument("--profile", "-p", required=True, help="Target profile")
    import_parser.add_argument("--password", help="Decryption password")
    
    args = parser.parse_args()
    
    cli = AdapterCLI()
    
    if args.command == "detect":
        cli.detect()
    elif args.command == "configure":
        cli.configure(args.profile, args.output)
    elif args.command == "list":
        cli.list_profiles()
    elif args.command == "export":
        cli.export_state(args.output, args.password)
    elif args.command == "import":
        cli.import_state(args.input, args.profile, args.password)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
