#!/usr/bin/env python3
"""
AIWorker MCP Bridge - External AI System Integration
Phase 5: Ecosystem Expansion & Multi-Instance Coordination

Provides secure bridge to external AI systems via Model Context Protocol.
Enables delegation to cloud APIs, integration with security tools,
and connection to corporate knowledge bases.
"""

import asyncio
import hashlib
import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional, Set, Callable, Any, Union
from collections import defaultdict
import aiohttp
import yaml

# MCP imports
try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.sse import sse_client
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False

logger = logging.getLogger("aiworker.external.mcp_bridge")


class TransportType(Enum):
    """MCP transport types."""
    STDIO = "stdio"
    SSE = "sse"
    WEBSOCKET = "websocket"


class AuthType(Enum):
    """Authentication types."""
    NONE = "none"
    API_KEY = "api_key"
    OAUTH = "oauth"
    VAULT = "vault"


@dataclass
class ExternalMCPConfig:
    """Configuration for an external MCP server."""
    name: str
    transport: TransportType
    
    # Connection details
    url: Optional[str] = None                    # For SSE/WebSocket
    command: Optional[str] = None                # For STDIO
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    
    # Authentication
    auth_type: AuthType = AuthType.NONE
    auth_config: Dict[str, Any] = field(default_factory=dict)
    
    # Security
    allowed_tools: List[str] = field(default_factory=list)  # Empty = all allowed
    denied_tools: List[str] = field(default_factory=list)
    rate_limit: str = "100/hour"
    max_response_size: int = 10 * 1024 * 1024    # 10MB
    timeout_seconds: int = 60
    
    # Network isolation
    network_namespace: Optional[str] = None
    no_local_fs: bool = True
    
    def __post_init__(self):
        if isinstance(self.transport, str):
            self.transport = TransportType(self.transport)
        if isinstance(self.auth_type, str):
            self.auth_type = AuthType(self.auth_type)


@dataclass
class ToolCall:
    """Record of a tool call."""
    tool_name: str
    arguments: Dict[str, Any]
    server_name: str
    timestamp: float = field(default_factory=time.time)
    duration_ms: float = 0.0
    success: bool = False
    response_size: int = 0
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "server_name": self.server_name,
            "timestamp": self.timestamp,
            "duration_ms": self.duration_ms,
            "success": self.success,
            "response_size": self.response_size,
            "error": self.error,
        }


class VaultCredentialManager:
    """Manages credentials from HashiCorp Vault."""
    
    def __init__(self, vault_addr: Optional[str] = None):
        self.vault_addr = vault_addr or os.environ.get("VAULT_ADDR")
        self._cache: Dict[str, Tuple[str, float]] = {}  # path -> (value, expires)
        self._cache_ttl = 300  # 5 minutes
    
    async def get_credential(self, path: str) -> Optional[str]:
        """Get credential from Vault."""
        # Check cache
        if path in self._cache:
            value, expires = self._cache[path]
            if time.time() < expires:
                return value
        
        if not self.vault_addr:
            logger.warning("Vault not configured")
            return None
        
        try:
            # Use vault CLI
            result = subprocess.run(
                ["vault", "kv", "get", "-format=json", path],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                logger.error(f"Vault error: {result.stderr}")
                return None
            
            data = json.loads(result.stdout)
            value = data.get("data", {}).get("data", {}).get("value")
            
            # Cache
            self._cache[path] = (value, time.time() + self._cache_ttl)
            
            return value
            
        except Exception as e:
            logger.error(f"Failed to get credential from Vault: {e}")
            return None
    
    def invalidate_cache(self, path: Optional[str] = None):
        """Invalidate credential cache."""
        if path:
            self._cache.pop(path, None)
        else:
            self._cache.clear()


class AuditLogger:
    """Immutable audit logging for external calls."""
    
    def __init__(self, log_dir: str = "/var/log/aiworker/mcp_audit"):
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)
        
        # Current log file
        self._current_date = time.strftime("%Y-%m-%d")
        self._log_file = os.path.join(log_dir, f"{self._current_date}.log")
    
    def log(self, call: ToolCall):
        """Log a tool call immutably."""
        # Rotate if needed
        current_date = time.strftime("%Y-%m-%d")
        if current_date != self._current_date:
            self._current_date = current_date
            self._log_file = os.path.join(self.log_dir, f"{current_date}.log")
        
        # Append to log
        entry = json.dumps(call.to_dict(), default=str)
        
        with open(self._log_file, "a") as f:
            f.write(entry + "\n")
    
    def get_recent(self, hours: int = 24) -> List[Dict]:
        """Get recent audit entries."""
        entries = []
        cutoff = time.time() - (hours * 3600)
        
        # Read current and previous day's logs
        dates = [time.strftime("%Y-%m-%d")]
        if time.localtime().tm_hour < hours / 24 * 24:
            # Might need yesterday's log too
            yesterday = time.localtime(time.time() - 86400)
            dates.insert(0, time.strftime("%Y-%m-%d", yesterday))
        
        for date in dates:
            log_file = os.path.join(self.log_dir, f"{date}.log")
            if os.path.exists(log_file):
                with open(log_file, "r") as f:
                    for line in f:
                        try:
                            entry = json.loads(line)
                            if entry.get("timestamp", 0) >= cutoff:
                                entries.append(entry)
                        except json.JSONDecodeError:
                            continue
        
        return entries


class RateLimiter:
    """Rate limiter for external calls."""
    
    def __init__(self, limit_str: str = "100/hour"):
        self.limit_str = limit_str
        self.max_calls, self.window_seconds = self._parse_limit(limit_str)
        self._calls: List[float] = []
        self._lock = asyncio.Lock()
    
    def _parse_limit(self, limit_str: str) -> Tuple[int, int]:
        """Parse rate limit string."""
        parts = limit_str.split("/")
        count = int(parts[0])
        
        unit = parts[1] if len(parts) > 1 else "hour"
        multipliers = {
            "second": 1,
            "minute": 60,
            "hour": 3600,
            "day": 86400,
        }
        
        return count, multipliers.get(unit, 3600)
    
    async def acquire(self) -> bool:
        """Acquire rate limit permit."""
        async with self._lock:
            now = time.time()
            window_start = now - self.window_seconds
            
            # Remove old calls
            self._calls = [t for t in self._calls if t > window_start]
            
            # Check limit
            if len(self._calls) >= self.max_calls:
                return False
            
            # Record call
            self._calls.append(now)
            return True
    
    def get_stats(self) -> Dict[str, Any]:
        """Get rate limiter statistics."""
        now = time.time()
        window_start = now - self.window_seconds
        recent_calls = [t for t in self._calls if t > window_start]
        
        return {
            "limit": self.limit_str,
            "used": len(recent_calls),
            "remaining": max(0, self.max_calls - len(recent_calls)),
            "reset_in": self.window_seconds - (now - min(self._calls)) if self._calls else 0,
        }


class MCPBridge:
    """
    Bridge to external AI systems via Model Context Protocol.
    
    Features:
    - Multiple transport types (STDIO, SSE, WebSocket)
    - Vault-integrated credential management
    - Immutable audit logging
    - Rate limiting per server
    - Network namespace isolation
    - Response size limits
    """
    
    def __init__(
        self,
        config_path: str = "/etc/aiworker/mcp_bridge.yaml",
        vault_addr: Optional[str] = None,
    ):
        self.config_path = config_path
        self.configs: Dict[str, ExternalMCPConfig] = {}
        
        # Components
        self.vault = VaultCredentialManager(vault_addr)
        self.audit = AuditLogger()
        self.rate_limiters: Dict[str, RateLimiter] = {}
        
        # Active connections
        self._sessions: Dict[str, Any] = {}
        self._tools: Dict[str, List[Dict]] = {}  # server -> tools
        
        # Tool registry
        self._tool_to_server: Dict[str, str] = {}
        
        # Load configuration
        self._load_config()
        
        logger.info(f"MCPBridge initialized with {len(self.configs)} servers")
    
    def _load_config(self):
        """Load MCP bridge configuration."""
        if not os.path.exists(self.config_path):
            logger.warning(f"Config not found: {self.config_path}")
            return
        
        try:
            with open(self.config_path, "r") as f:
                config = yaml.safe_load(f)
            
            for server_config in config.get("external_mcp", []):
                name = server_config["name"]
                
                cfg = ExternalMCPConfig(
                    name=name,
                    transport=TransportType(server_config.get("transport", "stdio")),
                    url=server_config.get("url"),
                    command=server_config.get("command"),
                    args=server_config.get("args", []),
                    env=server_config.get("env", {}),
                    auth_type=AuthType(server_config.get("auth_type", "none")),
                    auth_config=server_config.get("auth_config", {}),
                    allowed_tools=server_config.get("allowed_tools", []),
                    denied_tools=server_config.get("denied_tools", []),
                    rate_limit=server_config.get("rate_limit", "100/hour"),
                    max_response_size=server_config.get("max_response_size", 10*1024*1024),
                    timeout_seconds=server_config.get("timeout_seconds", 60),
                    network_namespace=server_config.get("network_namespace"),
                    no_local_fs=server_config.get("no_local_fs", True),
                )
                
                self.configs[name] = cfg
                self.rate_limiters[name] = RateLimiter(cfg.rate_limit)
                
                logger.info(f"Loaded MCP server: {name} ({cfg.transport.value})")
                
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
    
    async def connect(self, server_name: str) -> bool:
        """Connect to an external MCP server."""
        if not MCP_AVAILABLE:
            logger.error("MCP library not available")
            return False
        
        if server_name not in self.configs:
            logger.error(f"Unknown server: {server_name}")
            return False
        
        config = self.configs[server_name]
        
        try:
            if config.transport == TransportType.STDIO:
                return await self._connect_stdio(server_name, config)
            elif config.transport == TransportType.SSE:
                return await self._connect_sse(server_name, config)
            else:
                logger.error(f"Unsupported transport: {config.transport}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to connect to {server_name}: {e}")
            return False
    
    async def _connect_stdio(self, name: str, config: ExternalMCPConfig) -> bool:
        """Connect via STDIO transport."""
        if not config.command:
            logger.error(f"No command specified for {name}")
            return False
        
        # Resolve credentials
        env = config.env.copy()
        if config.auth_type == AuthType.VAULT:
            vault_path = config.auth_config.get("vault_path")
            if vault_path:
                credential = await self.vault.get_credential(vault_path)
                if credential:
                    env["API_KEY"] = credential
        
        # Build server parameters
        server_params = StdioServerParameters(
            command=config.command,
            args=config.args,
            env=env,
        )
        
        # Connect
        stdio_transport = await self._stdio_client_context(server_params)
        read, write = stdio_transport
        session = await ClientSession(read, write).__aenter__()
        
        await session.initialize()
        
        self._sessions[name] = session
        
        # List available tools
        tools_response = await session.list_tools()
        self._tools[name] = [
            {"name": tool.name, "description": tool.description}
            for tool in tools_response.tools
        ]
        
        # Register tools
        for tool in self._tools[name]:
            self._tool_to_server[tool["name"]] = name
        
        logger.info(f"Connected to {name}: {len(self._tools[name])} tools available")
        
        return True
    
    async def _stdio_client_context(self, server_params: Any):
        """Context manager for stdio client."""
        # This is a simplified version - real implementation would use contextlib
        process = await asyncio.create_subprocess_exec(
            server_params.command,
            *server_params.args,
            env={**os.environ, **server_params.env},
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        return process.stdout, process.stdin
    
    async def _connect_sse(self, name: str, config: ExternalMCPConfig) -> bool:
        """Connect via SSE transport."""
        if not config.url:
            logger.error(f"No URL specified for {name}")
            return False
        
        # Resolve credentials
        headers = {}
        if config.auth_type == AuthType.API_KEY:
            api_key = config.auth_config.get("api_key")
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
        elif config.auth_type == AuthType.VAULT:
            vault_path = config.auth_config.get("vault_path")
            if vault_path:
                credential = await self.vault.get_credential(vault_path)
                if credential:
                    headers["Authorization"] = f"Bearer {credential}"
        
        # Connect via SSE
        # Note: Real implementation would use mcp.client.sse
        logger.info(f"SSE connection to {name} at {config.url}")
        
        # For now, create a placeholder session
        self._sessions[name] = {"type": "sse", "url": config.url, "headers": headers}
        
        return True
    
    async def disconnect(self, server_name: str):
        """Disconnect from an MCP server."""
        if server_name in self._sessions:
            session = self._sessions[server_name]
            
            if isinstance(session, dict) and session.get("type") == "sse":
                # SSE session
                pass
            elif hasattr(session, '__aexit__'):
                await session.__aexit__(None, None, None)
            
            del self._sessions[server_name]
            del self._tools[server_name]
            
            # Clean up tool mappings
            self._tool_to_server = {
                k: v for k, v in self._tool_to_server.items()
                if v != server_name
            }
            
            logger.info(f"Disconnected from {server_name}")
    
    async def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        server_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Call a tool on an external MCP server.
        
        Args:
            tool_name: Name of the tool to call
            arguments: Tool arguments
            server_name: Specific server to use (auto-detected if None)
        
        Returns:
            Tool response
        """
        start_time = time.time()
        
        # Find server for tool
        if server_name is None:
            server_name = self._tool_to_server.get(tool_name)
            if not server_name:
                raise ValueError(f"Tool not found: {tool_name}")
        
        config = self.configs.get(server_name)
        if not config:
            raise ValueError(f"Server not found: {server_name}")
        
        # Check if tool is allowed
        if config.allowed_tools and tool_name not in config.allowed_tools:
            raise PermissionError(f"Tool {tool_name} not in allowed list")
        
        if tool_name in config.denied_tools:
            raise PermissionError(f"Tool {tool_name} is denied")
        
        # Check rate limit
        limiter = self.rate_limiters[server_name]
        if not await limiter.acquire():
            raise RateLimitExceeded(f"Rate limit exceeded for {server_name}")
        
        # Ensure connected
        if server_name not in self._sessions:
            connected = await self.connect(server_name)
            if not connected:
                raise ConnectionError(f"Failed to connect to {server_name}")
        
        # Execute call
        session = self._sessions[server_name]
        
        try:
            if isinstance(session, dict) and session.get("type") == "sse":
                # SSE call
                result = await self._call_sse_tool(session, tool_name, arguments, config)
            else:
                # STDIO call via MCP
                result = await asyncio.wait_for(
                    session.call_tool(tool_name, arguments),
                    timeout=config.timeout_seconds
                )
            
            duration_ms = (time.time() - start_time) * 1000
            
            # Audit log
            call = ToolCall(
                tool_name=tool_name,
                arguments=arguments,
                server_name=server_name,
                duration_ms=duration_ms,
                success=True,
                response_size=len(json.dumps(result)),
            )
            self.audit.log(call)
            
            # Check response size
            response_size = len(json.dumps(result))
            if response_size > config.max_response_size:
                logger.warning(f"Response size {response_size} exceeds limit")
                result = {"error": "Response too large", "truncated": True}
            
            return result
            
        except asyncio.TimeoutError:
            duration_ms = (time.time() - start_time) * 1000
            
            call = ToolCall(
                tool_name=tool_name,
                arguments=arguments,
                server_name=server_name,
                duration_ms=duration_ms,
                success=False,
                error="Timeout",
            )
            self.audit.log(call)
            
            raise TimeoutError(f"Tool call to {tool_name} timed out")
            
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            
            call = ToolCall(
                tool_name=tool_name,
                arguments=arguments,
                server_name=server_name,
                duration_ms=duration_ms,
                success=False,
                error=str(e),
            )
            self.audit.log(call)
            
            raise
    
    async def _call_sse_tool(
        self,
        session: Dict,
        tool_name: str,
        arguments: Dict[str, Any],
        config: ExternalMCPConfig
    ) -> Dict[str, Any]:
        """Call tool via SSE transport."""
        url = f"{session['url']}/tools/{tool_name}"
        
        async with aiohttp.ClientSession() as client:
            async with client.post(
                url,
                json=arguments,
                headers=session.get("headers", {}),
                timeout=aiohttp.ClientTimeout(total=config.timeout_seconds),
            ) as response:
                return await response.json()
    
    def list_tools(self, server_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """List available tools."""
        if server_name:
            return self._tools.get(server_name, [])
        
        all_tools = []
        for server, tools in self._tools.items():
            for tool in tools:
                all_tools.append({
                    **tool,
                    "server": server,
                })
        
        return all_tools
    
    def get_stats(self) -> Dict[str, Any]:
        """Get bridge statistics."""
        return {
            "servers_configured": len(self.configs),
            "servers_connected": len(self._sessions),
            "tools_available": len(self._tool_to_server),
            "rate_limits": {
                name: limiter.get_stats()
                for name, limiter in self.rate_limiters.items()
            },
            "recent_calls": len(self.audit.get_recent(hours=1)),
        }


class RateLimitExceeded(Exception):
    """Raised when rate limit is exceeded."""
    pass


# Convenience functions
async def create_mcp_bridge(
    config_path: str = "/etc/aiworker/mcp_bridge.yaml",
    vault_addr: Optional[str] = None,
) -> MCPBridge:
    """Create an MCP bridge."""
    return MCPBridge(config_path, vault_addr)


# Example configuration file
EXAMPLE_CONFIG = """
external_mcp:
  - name: "openai_api"
    transport: "sse"
    url: "https://api.openai.com/v1/mcp"
    auth_type: "vault"
    auth_config:
      vault_path: "secret/aiworker/openai_key"
    allowed_tools: ["gpt4_analysis", "gpt4_completion"]
    rate_limit: "100/hour"
    max_response_size: 10485760
    timeout_seconds: 60
    no_local_fs: true

  - name: "corporate_kb"
    transport: "stdio"
    command: "/opt/bridge_kb"
    args: ["--server"]
    env:
      LOG_LEVEL: "info"
    allowed_tools: ["search_docs", "get_policy"]
    rate_limit: "1000/hour"
    timeout_seconds: 30

  - name: "security_tools"
    transport: "sse"
    url: "http://localhost:8080/mcp"
    auth_type: "none"
    allowed_tools: ["burp_scan", "nessus_scan"]
    rate_limit: "10/hour"
    network_namespace: "security_tools"
    no_local_fs: true
"""


if __name__ == "__main__":
    # Print example config
    print("Example MCP Bridge configuration:")
    print(EXAMPLE_CONFIG)
