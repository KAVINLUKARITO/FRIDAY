#!/usr/bin/env python3
"""
AIWorker Mesh Network Node - Decentralized P2P Networking
Phase 5: Ecosystem Expansion & Multi-Instance Coordination

Provides decentralized peer-to-peer networking for AIWorker instances with:
- Ed25519 cryptographic identity
- Encrypted communication (Noise Protocol)
- DHT-based peer discovery
- Role-based node specialization
- 32GB memory optimization
"""

import asyncio
import hashlib
import json
import logging
import struct
import time
import zlib
from dataclasses import dataclass, field, asdict
from enum import Enum, auto
from typing import Dict, List, Optional, Set, Callable, Any, Tuple
import secrets

# Cryptographic imports
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# Noise protocol for encrypted channels
try:
    from noise.connection import NoiseConnection, Keypair
    NOISE_AVAILABLE = True
except ImportError:
    NOISE_AVAILABLE = False

# Configure logging
logger = logging.getLogger("aiworker.mesh.node")


class NodeRole(Enum):
    """Node specialization roles in the mesh."""
    WORKER = "worker"           # General purpose, accepts tasks
    SPECIALIST = "specialist"   # Optimized for specific work
    COORDINATOR = "coordinator" # Temporary leader for task distribution
    OBSERVER = "observer"       # Read-only, monitoring network health


class MessageType(Enum):
    """Protocol message types."""
    PING = auto()
    PONG = auto()
    ANNOUNCE = auto()
    TASK_OFFER = auto()
    TASK_ACCEPT = auto()
    TASK_COMPLETE = auto()
    SYNC_REQUEST = auto()
    SYNC_RESPONSE = auto()
    PEER_DISCOVER = auto()
    PEER_ANNOUNCE = auto()
    COORDINATOR_ELECT = auto()
    COORDINATOR_ACCEPT = auto()
    BLACKLIST_UPDATE = auto()


@dataclass
class MeshConfig:
    """Configuration for mesh network node."""
    node_id: str = ""                          # Derived from public key
    listen_addr: str = "0.0.0.0:0"              # Bind address
    bootstrap_peers: List[str] = field(default_factory=list)
    max_peers: int = 10                         # 32GB constraint
    role: str = "WORKER"
    sync_interval_minutes: int = 360            # 6 hours
    
    # Security settings
    enable_encryption: bool = True
    require_auth: bool = True
    rate_limit_per_minute: int = 60
    
    # Network settings
    connection_timeout: int = 30
    ping_interval: int = 60
    peer_ttl: int = 300                         # Peer expires after 5 min silence
    
    # Compression
    compression_level: int = 3                  # zstd level
    max_message_size: int = 10 * 1024 * 1024    # 10MB
    
    def __post_init__(self):
        if not self.node_id:
            self.node_id = self._generate_node_id()
    
    def _generate_node_id(self) -> str:
        """Generate a unique node ID based on hostname and time."""
        import socket
        unique = f"{socket.gethostname()}:{time.time()}:{secrets.token_hex(8)}"
        return hashlib.sha256(unique.encode()).hexdigest()[:32]


@dataclass
class NodeCapabilities:
    """Capabilities advertised by a node."""
    ram_gb: int = 32
    cpu_cores: int = 4
    has_gpu: bool = False
    gpu_vram_gb: int = 0
    disk_speed_mbps: int = 100
    network_mbps: int = 1000
    
    # AI-specific
    models_cached: List[str] = field(default_factory=list)
    skills_available: List[str] = field(default_factory=list)
    
    # Load metrics
    current_load: float = 0.0                   # 0.0 - 1.0
    active_tasks: int = 0
    queue_depth: int = 0
    
    # Role-specific
    specialization: str = "general"
    success_rate: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NodeCapabilities":
        return cls(**data)


@dataclass
class PeerInfo:
    """Information about a connected peer."""
    node_id: str
    role: NodeRole
    capabilities: NodeCapabilities
    address: Tuple[str, int]
    public_key: Optional[bytes] = None
    
    # Connection state
    connected_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    messages_sent: int = 0
    messages_received: int = 0
    bytes_transferred: int = 0
    
    # Rate limiting
    message_count: Dict[int, int] = field(default_factory=dict)  # minute -> count
    
    # Trust
    trust_score: float = 1.0
    violations: int = 0
    
    def is_expired(self, ttl: int = 300) -> bool:
        """Check if peer has timed out."""
        return time.time() - self.last_seen > ttl
    
    def update_activity(self):
        """Update last seen timestamp."""
        self.last_seen = time.time()


@dataclass
class MeshMessage:
    """Message structure for mesh protocol."""
    msg_type: MessageType
    sender_id: str
    payload: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    signature: Optional[bytes] = None
    message_id: str = field(default_factory=lambda: secrets.token_hex(16))
    
    def to_bytes(self) -> bytes:
        """Serialize message to bytes."""
        data = {
            "msg_type": self.msg_type.name,
            "sender_id": self.sender_id,
            "payload": self.payload,
            "timestamp": self.timestamp,
            "message_id": self.message_id,
        }
        return json.dumps(data, default=str).encode()
    
    @classmethod
    def from_bytes(cls, data: bytes) -> "MeshMessage":
        """Deserialize message from bytes."""
        obj = json.loads(data.decode())
        return cls(
            msg_type=MessageType[obj["msg_type"]],
            sender_id=obj["sender_id"],
            payload=obj["payload"],
            timestamp=obj["timestamp"],
            message_id=obj["message_id"],
        )
    
    def sign(self, private_key: Ed25519PrivateKey):
        """Sign the message with node's private key."""
        data = self.to_bytes()
        self.signature = private_key.sign(data)
    
    def verify(self, public_key: Ed25519PublicKey) -> bool:
        """Verify message signature."""
        if not self.signature:
            return False
        try:
            data = self.to_bytes()
            public_key.verify(self.signature, data)
            return True
        except Exception:
            return False


class ConnectionPool:
    """Pool of reusable TCP connections to peers."""
    
    def __init__(self, max_connections: int = 10):
        self.max_connections = max_connections
        self.connections: Dict[str, asyncio.Transport] = {}
        self.lock = asyncio.Lock()
        self._protocols: Dict[str, "MeshProtocol"] = {}
    
    async def get_connection(self, node_id: str) -> Optional[asyncio.Transport]:
        """Get existing connection to peer."""
        async with self.lock:
            return self.connections.get(node_id)
    
    async def add_connection(
        self, 
        node_id: str, 
        transport: asyncio.Transport,
        protocol: "MeshProtocol"
    ):
        """Add connection to pool."""
        async with self.lock:
            if len(self.connections) >= self.max_connections:
                # Remove oldest connection
                oldest = min(self.connections.keys(), 
                           key=lambda k: self._protocols[k].connected_at)
                await self.remove_connection(oldest)
            
            self.connections[node_id] = transport
            self._protocols[node_id] = protocol
    
    async def remove_connection(self, node_id: str):
        """Remove connection from pool."""
        async with self.lock:
            if node_id in self.connections:
                transport = self.connections.pop(node_id)
                try:
                    transport.close()
                except Exception:
                    pass
                self._protocols.pop(node_id, None)
    
    async def broadcast(self, message: bytes, exclude: Optional[Set[str]] = None):
        """Broadcast message to all connected peers."""
        exclude = exclude or set()
        async with self.lock:
            for node_id, transport in self.connections.items():
                if node_id not in exclude:
                    try:
                        transport.write(message)
                    except Exception as e:
                        logger.warning(f"Failed to send to {node_id}: {e}")


class MeshProtocol(asyncio.Protocol):
    """Asyncio protocol handler for mesh connections."""
    
    def __init__(self, node: "MeshNode", is_outbound: bool = False):
        self.node = node
        self.is_outbound = is_outbound
        self.transport: Optional[asyncio.Transport] = None
        self.peer_id: Optional[str] = None
        self.connected_at: float = 0.0
        self.buffer = b""
        self.message_size: Optional[int] = None
        self.noise: Optional[Any] = None
        self._handshake_complete = False
    
    def connection_made(self, transport: asyncio.Transport):
        """Called when connection is established."""
        self.transport = transport
        self.connected_at = time.time()
        
        if NOISE_AVAILABLE and self.node.config.enable_encryption:
            self._init_noise()
        else:
            self._handshake_complete = True
        
        logger.debug(f"Connection made (outbound={self.is_outbound})")
    
    def _init_noise(self):
        """Initialize Noise protocol for encryption."""
        if not NOISE_AVAILABLE:
            return
        
        pattern = "Noise_XX_25519_ChaChaPoly_BLAKE2s"
        self.noise = NoiseConnection.from_name(pattern)
        
        if self.is_outbound:
            self.noise.set_as_initiator()
        else:
            self.noise.set_as_responder()
        
        self.noise.start_handshake()
    
    def data_received(self, data: bytes):
        """Called when data is received."""
        self.buffer += data
        
        # Handle Noise handshake if encryption enabled
        if self.noise and not self._handshake_complete:
            self._handle_handshake()
            return
        
        # Process complete messages
        while self._has_complete_message():
            message = self._extract_message()
            if message:
                asyncio.create_task(self._process_message(message))
    
    def _handle_handshake(self):
        """Handle Noise protocol handshake."""
        if not self.noise:
            return
        
        try:
            self.noise.read_message(self.buffer)
            self.buffer = b""
            
            if self.noise.handshake_finished:
                self._handshake_complete = True
                logger.debug("Noise handshake complete")
        except Exception as e:
            logger.warning(f"Handshake failed: {e}")
            self.transport.close()
    
    def _has_complete_message(self) -> bool:
        """Check if buffer contains a complete message."""
        if len(self.buffer) < 4:
            return False
        
        if self.message_size is None:
            self.message_size = struct.unpack("!I", self.buffer[:4])[0]
        
        return len(self.buffer) >= 4 + self.message_size
    
    def _extract_message(self) -> Optional[bytes]:
        """Extract complete message from buffer."""
        if not self._has_complete_message():
            return None
        
        size = self.message_size
        message = self.buffer[4:4+size]
        self.buffer = self.buffer[4+size:]
        self.message_size = None
        
        # Decrypt if needed
        if self.noise and self._handshake_complete:
            try:
                message = self.noise.decrypt(message)
            except Exception as e:
                logger.warning(f"Decryption failed: {e}")
                return None
        
        # Decompress
        try:
            message = zlib.decompress(message)
        except zlib.error:
            pass  # Not compressed
        
        return message
    
    async def _process_message(self, data: bytes):
        """Process received message."""
        try:
            message = MeshMessage.from_bytes(data)
            
            # Update peer activity
            if message.sender_id in self.node.peers:
                self.node.peers[message.sender_id].update_activity()
                self.node.peers[message.sender_id].messages_received += 1
            
            # Verify signature if required
            if self.node.config.require_auth and message.sender_id in self.node._peer_keys:
                public_key = self.node._peer_keys[message.sender_id]
                if not message.verify(public_key):
                    logger.warning(f"Invalid signature from {message.sender_id}")
                    await self.node._handle_violation(message.sender_id, "bad_signature")
                    return
            
            # Route to handler
            await self.node._handle_message(message, self)
            
        except Exception as e:
            logger.error(f"Failed to process message: {e}")
    
    def send_message(self, message: MeshMessage):
        """Send message to peer."""
        if not self.transport:
            return
        
        data = message.to_bytes()
        
        # Compress
        compressed = zlib.compress(data, level=self.node.config.compression_level)
        
        # Encrypt if needed
        if self.noise and self._handshake_complete:
            compressed = self.noise.encrypt(compressed)
        
        # Add length prefix
        packet = struct.pack("!I", len(compressed)) + compressed
        
        self.transport.write(packet)
        
        # Update stats
        if self.peer_id in self.node.peers:
            self.node.peers[self.peer_id].messages_sent += 1
            self.node.peers[self.peer_id].bytes_transferred += len(packet)
    
    def connection_lost(self, exc: Optional[Exception]):
        """Called when connection is lost."""
        if self.peer_id:
            logger.info(f"Connection lost to {self.peer_id}")
            asyncio.create_task(self.node._handle_disconnect(self.peer_id))


class MeshNode:
    """
    Decentralized P2P network node for AIWorker mesh.
    
    Features:
    - Ed25519 cryptographic identity
    - Encrypted peer-to-peer communication
    - Role-based specialization
    - Automatic peer discovery
    - Rate limiting and blacklisting
    """
    
    def __init__(self, config: Optional[MeshConfig] = None):
        self.config = config or MeshConfig()
        self.role = NodeRole(self.config.role)
        
        # Cryptographic identity
        self._private_key: Optional[Ed25519PrivateKey] = None
        self._public_key: Optional[Ed25519PublicKey] = None
        self._init_identity()
        
        # Peers and connections
        self.peers: Dict[str, PeerInfo] = {}
        self._peer_keys: Dict[str, Ed25519PublicKey] = {}
        self._blacklist: Set[str] = set()
        self.connection_pool = ConnectionPool(self.config.max_peers)
        
        # Server
        self._server: Optional[asyncio.Server] = None
        self._running = False
        
        # Capabilities
        self.capabilities = self._detect_capabilities()
        
        # Handlers
        self._message_handlers: Dict[MessageType, List[Callable]] = {
            msg_type: [] for msg_type in MessageType
        }
        
        # Background tasks
        self._tasks: List[asyncio.Task] = []
        
        # Coordinator election
        self._coordinator_id: Optional[str] = None
        self._election_in_progress = False
        
        logger.info(f"MeshNode initialized: {self.config.node_id} (role={self.role.value})")
    
    def _init_identity(self):
        """Initialize or load cryptographic identity."""
        key_path = f"/var/lib/aiworker/keys/{self.config.node_id}.key"
        
        try:
            # Try to load existing key
            with open(key_path, "rb") as f:
                key_data = f.read()
                self._private_key = Ed25519PrivateKey.from_private_bytes(key_data)
        except FileNotFoundError:
            # Generate new keypair
            self._private_key = Ed25519PrivateKey.generate()
            
            # Save key
            import os
            os.makedirs(os.path.dirname(key_path), exist_ok=True)
            key_data = self._private_key.private_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PrivateFormat.Raw,
                encryption_algorithm=serialization.NoEncryption()
            )
            with open(key_path, "wb") as f:
                f.write(key_data)
        
        self._public_key = self._private_key.public_key()
        
        # Update node_id to match public key
        public_bytes = self._public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw
        )
        self.config.node_id = hashlib.sha256(public_bytes).hexdigest()[:32]
    
    def _detect_capabilities(self) -> NodeCapabilities:
        """Auto-detect system capabilities."""
        import psutil
        
        mem = psutil.virtual_memory()
        cpu = psutil.cpu_count(logical=True)
        
        caps = NodeCapabilities(
            ram_gb=mem.total // (1024**3),
            cpu_cores=cpu,
            current_load=psutil.getloadavg()[0] / cpu if cpu else 0.0,
        )
        
        # Check for GPU
        try:
            import torch
            if torch.cuda.is_available():
                caps.has_gpu = True
                caps.gpu_vram_gb = torch.cuda.get_device_properties(0).total_memory // (1024**3)
        except ImportError:
            pass
        
        return caps
    
    async def start(self) -> str:
        """Start the mesh node server."""
        if self._running:
            return self.get_listen_addr()
        
        # Start TCP server
        host, port_str = self.config.listen_addr.rsplit(":", 1)
        port = int(port_str) if port_str != "0" else 0
        
        self._server = await asyncio.start_server(
            self._handle_incoming,
            host=host,
            port=port,
        )
        
        self._running = True
        
        # Start background tasks
        self._tasks.append(asyncio.create_task(self._ping_loop()))
        self._tasks.append(asyncio.create_task(self._cleanup_loop()))
        self._tasks.append(asyncio.create_task(self._discovery_loop()))
        
        # Connect to bootstrap peers
        for peer_addr in self.config.bootstrap_peers:
            asyncio.create_task(self._connect_to_peer(peer_addr))
        
        listen_addr = self.get_listen_addr()
        logger.info(f"MeshNode listening on {listen_addr}")
        
        return listen_addr
    
    async def stop(self):
        """Stop the mesh node."""
        self._running = False
        
        # Cancel background tasks
        for task in self._tasks:
            task.cancel()
        
        # Close all connections
        await self.connection_pool.broadcast(b"")  # Signal shutdown
        
        # Close server
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        
        logger.info("MeshNode stopped")
    
    def get_listen_addr(self) -> str:
        """Get the actual listening address."""
        if not self._server:
            return ""
        
        sock = self._server.sockets[0]
        addr = sock.getsockname()
        return f"/ip4/{addr[0]}/tcp/{addr[1]}/p2p/{self.config.node_id}"
    
    def _handle_incoming(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle incoming connection."""
        protocol = MeshProtocol(self, is_outbound=False)
        protocol.connection_made(writer)
        
        async def read_loop():
            while self._running:
                try:
                    data = await reader.read(65536)
                    if not data:
                        break
                    protocol.data_received(data)
                except Exception as e:
                    logger.debug(f"Read error: {e}")
                    break
            
            protocol.connection_lost(None)
        
        asyncio.create_task(read_loop())
    
    async def _connect_to_peer(self, peer_addr: str) -> Optional[str]:
        """Connect to a bootstrap peer."""
        try:
            # Parse multiaddr-like format: /ip4/1.2.3.4/tcp/1234/p2p/QmNodeId
            parts = peer_addr.strip("/").split("/")
            ip = parts[parts.index("ip4") + 1]
            port = int(parts[parts.index("tcp") + 1])
            node_id = parts[parts.index("p2p") + 1] if "p2p" in parts else None
            
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port),
                timeout=self.config.connection_timeout
            )
            
            protocol = MeshProtocol(self, is_outbound=True)
            protocol.peer_id = node_id
            protocol.connection_made(writer)
            
            # Start read loop
            async def read_loop():
                while self._running:
                    try:
                        data = await reader.read(65536)
                        if not data:
                            break
                        protocol.data_received(data)
                    except Exception:
                        break
                protocol.connection_lost(None)
            
            asyncio.create_task(read_loop())
            
            # Send announcement
            await self._send_announcement(protocol)
            
            return node_id
            
        except Exception as e:
            logger.warning(f"Failed to connect to {peer_addr}: {e}")
            return None
    
    async def _send_announcement(self, protocol: MeshProtocol):
        """Send capability announcement to peer."""
        message = MeshMessage(
            msg_type=MessageType.ANNOUNCE,
            sender_id=self.config.node_id,
            payload={
                "role": self.role.value,
                "capabilities": self.capabilities.to_dict(),
                "listen_addr": self.get_listen_addr(),
                "public_key": self._public_key.public_bytes(
                    encoding=serialization.Encoding.Raw,
                    format=serialization.PublicFormat.Raw
                ).hex(),
            }
        )
        message.sign(self._private_key)
        protocol.send_message(message)
    
    async def _handle_message(self, message: MeshMessage, protocol: MeshProtocol):
        """Route message to appropriate handler."""
        # Update peer info from protocol
        if protocol.peer_id:
            message.sender_id = protocol.peer_id
        
        # Check blacklist
        if message.sender_id in self._blacklist:
            logger.debug(f"Ignoring message from blacklisted peer {message.sender_id}")
            return
        
        # Rate limiting
        if not self._check_rate_limit(message.sender_id):
            logger.warning(f"Rate limit exceeded for {message.sender_id}")
            await self._handle_violation(message.sender_id, "rate_limit")
            return
        
        # Route to handlers
        handlers = self._message_handlers.get(message.msg_type, [])
        for handler in handlers:
            try:
                await handler(message, protocol)
            except Exception as e:
                logger.error(f"Handler error: {e}")
        
        # Built-in handlers
        await self._handle_builtin(message, protocol)
    
    async def _handle_builtin(self, message: MeshMessage, protocol: MeshProtocol):
        """Handle built-in message types."""
        if message.msg_type == MessageType.PING:
            await self._handle_ping(message, protocol)
        elif message.msg_type == MessageType.ANNOUNCE:
            await self._handle_announce(message, protocol)
        elif message.msg_type == MessageType.PEER_DISCOVER:
            await self._handle_peer_discover(message, protocol)
        elif message.msg_type == MessageType.COORDINATOR_ELECT:
            await self._handle_coordinator_elect(message, protocol)
    
    async def _handle_ping(self, message: MeshMessage, protocol: MeshProtocol):
        """Respond to ping with pong."""
        pong = MeshMessage(
            msg_type=MessageType.PONG,
            sender_id=self.config.node_id,
            payload={"timestamp": time.time()}
        )
        pong.sign(self._private_key)
        protocol.send_message(pong)
    
    async def _handle_announce(self, message: MeshMessage, protocol: MeshProtocol):
        """Handle peer announcement."""
        payload = message.payload
        node_id = message.sender_id
        
        # Store peer info
        capabilities = NodeCapabilities.from_dict(payload.get("capabilities", {}))
        
        peer_info = PeerInfo(
            node_id=node_id,
            role=NodeRole(payload.get("role", "worker")),
            capabilities=capabilities,
            address=("", 0),  # Will be updated
            public_key=bytes.fromhex(payload.get("public_key", "00")),
        )
        
        self.peers[node_id] = peer_info
        protocol.peer_id = node_id
        
        # Store public key for verification
        try:
            public_key = Ed25519PublicKey.from_public_bytes(peer_info.public_key)
            self._peer_keys[node_id] = public_key
        except Exception as e:
            logger.warning(f"Failed to load peer public key: {e}")
        
        logger.info(f"Peer announced: {node_id} ({peer_info.role.value})")
    
    async def _handle_peer_discover(self, message: MeshMessage, protocol: MeshProtocol):
        """Respond with known peers."""
        peers = []
        for node_id, peer in self.peers.items():
            if peer.trust_score > 0.5:  # Only share trusted peers
                peers.append({
                    "node_id": node_id,
                    "role": peer.role.value,
                    "listen_addr": peer.address,
                })
        
        response = MeshMessage(
            msg_type=MessageType.PEER_ANNOUNCE,
            sender_id=self.config.node_id,
            payload={"peers": peers[:10]}  # Limit to 10 peers
        )
        response.sign(self._private_key)
        protocol.send_message(response)
    
    async def _handle_coordinator_elect(self, message: MeshMessage, protocol: MeshProtocol):
        """Handle coordinator election."""
        candidate_id = message.payload.get("candidate_id")
        
        # Simple election: accept if candidate has higher ID or we're not coordinator
        if self._coordinator_id is None or candidate_id > self._coordinator_id:
            self._coordinator_id = candidate_id
            
            # Accept
            accept = MeshMessage(
                msg_type=MessageType.COORDINATOR_ACCEPT,
                sender_id=self.config.node_id,
                payload={"coordinator_id": candidate_id}
            )
            accept.sign(self._private_key)
            protocol.send_message(accept)
            
            logger.info(f"Accepted {candidate_id} as coordinator")
    
    async def _handle_disconnect(self, node_id: str):
        """Handle peer disconnection."""
        await self.connection_pool.remove_connection(node_id)
        
        if node_id == self._coordinator_id:
            logger.warning("Coordinator disconnected, triggering re-election")
            self._coordinator_id = None
            await self._start_election()
    
    async def _handle_violation(self, node_id: str, violation_type: str):
        """Handle protocol violation by peer."""
        if node_id not in self.peers:
            return
        
        self.peers[node_id].violations += 1
        self.peers[node_id].trust_score *= 0.8
        
        if self.peers[node_id].violations >= 3:
            logger.warning(f"Blacklisting {node_id} due to repeated violations")
            self._blacklist.add(node_id)
            await self.connection_pool.remove_connection(node_id)
    
    def _check_rate_limit(self, node_id: str) -> bool:
        """Check if peer is within rate limit."""
        if node_id not in self.peers:
            return True
        
        peer = self.peers[node_id]
        current_minute = int(time.time()) // 60
        
        # Clean old entries
        peer.message_count = {
            k: v for k, v in peer.message_count.items() 
            if k >= current_minute - 1
        }
        
        # Check limit
        total = sum(peer.message_count.values())
        if total >= self.config.rate_limit_per_minute:
            return False
        
        peer.message_count[current_minute] = peer.message_count.get(current_minute, 0) + 1
        return True
    
    async def _ping_loop(self):
        """Periodically ping connected peers."""
        while self._running:
            try:
                await asyncio.sleep(self.config.ping_interval)
                
                for node_id in list(self.peers.keys()):
                    if node_id in self._blacklist:
                        continue
                    
                    ping = MeshMessage(
                        msg_type=MessageType.PING,
                        sender_id=self.config.node_id,
                        payload={"timestamp": time.time()}
                    )
                    ping.sign(self._private_key)
                    
                    # Get connection and send
                    transport = await self.connection_pool.get_connection(node_id)
                    if transport:
                        # Find protocol and send
                        for protocol in self.connection_pool._protocols.values():
                            if protocol.peer_id == node_id:
                                protocol.send_message(ping)
                                break
                    
            except Exception as e:
                logger.debug(f"Ping loop error: {e}")
    
    async def _cleanup_loop(self):
        """Remove expired peers."""
        while self._running:
            try:
                await asyncio.sleep(60)
                
                expired = [
                    node_id for node_id, peer in self.peers.items()
                    if peer.is_expired(self.config.peer_ttl)
                ]
                
                for node_id in expired:
                    logger.debug(f"Removing expired peer {node_id}")
                    del self.peers[node_id]
                    await self.connection_pool.remove_connection(node_id)
                    
            except Exception as e:
                logger.debug(f"Cleanup loop error: {e}")
    
    async def _discovery_loop(self):
        """Periodically discover new peers."""
        while self._running:
            try:
                await asyncio.sleep(300)  # Every 5 minutes
                
                if len(self.peers) < self.config.max_peers:
                    await self._discover_peers()
                    
            except Exception as e:
                logger.debug(f"Discovery loop error: {e}")
    
    async def _discover_peers(self):
        """Request peer lists from connected peers."""
        for node_id in list(self.peers.keys()):
            if node_id in self._blacklist:
                continue
            
            message = MeshMessage(
                msg_type=MessageType.PEER_DISCOVER,
                sender_id=self.config.node_id,
                payload={}
            )
            message.sign(self._private_key)
            
            # Send via connection pool
            for protocol in self.connection_pool._protocols.values():
                if protocol.peer_id == node_id:
                    protocol.send_message(message)
                    break
    
    async def _start_election(self):
        """Start coordinator election."""
        if self._election_in_progress:
            return
        
        self._election_in_progress = True
        
        try:
            # Simple bully algorithm: highest node ID wins
            all_ids = [self.config.node_id] + list(self.peers.keys())
            highest = max(all_ids)
            
            if highest == self.config.node_id:
                # We are the coordinator
                self._coordinator_id = self.config.node_id
                
                # Announce to all peers
                message = MeshMessage(
                    msg_type=MessageType.COORDINATOR_ELECT,
                    sender_id=self.config.node_id,
                    payload={"candidate_id": self.config.node_id}
                )
                message.sign(self._private_key)
                
                for protocol in self.connection_pool._protocols.values():
                    protocol.send_message(message)
                
                logger.info("Elected as coordinator")
                
        finally:
            self._election_in_progress = False
    
    def register_handler(self, msg_type: MessageType, handler: Callable):
        """Register a message handler."""
        self._message_handlers[msg_type].append(handler)
    
    async def broadcast(self, message: MeshMessage, exclude: Optional[Set[str]] = None):
        """Broadcast message to all peers."""
        message.sign(self._private_key)
        
        data = message.to_bytes()
        compressed = zlib.compress(data, level=self.config.compression_level)
        
        await self.connection_pool.broadcast(compressed, exclude)
    
    async def send_to(self, node_id: str, message: MeshMessage) -> bool:
        """Send message to specific peer."""
        if node_id not in self.peers:
            return False
        
        message.sign(self._private_key)
        
        for protocol in self.connection_pool._protocols.values():
            if protocol.peer_id == node_id:
                protocol.send_message(message)
                return True
        
        return False
    
    def get_coordinator(self) -> Optional[str]:
        """Get current coordinator node ID."""
        return self._coordinator_id
    
    def is_coordinator(self) -> bool:
        """Check if this node is the coordinator."""
        return self._coordinator_id == self.config.node_id
    
    def get_stats(self) -> Dict[str, Any]:
        """Get node statistics."""
        return {
            "node_id": self.config.node_id,
            "role": self.role.value,
            "peers_connected": len(self.peers),
            "coordinator": self._coordinator_id,
            "is_coordinator": self.is_coordinator(),
            "capabilities": self.capabilities.to_dict(),
            "listen_addr": self.get_listen_addr(),
            "blacklist_size": len(self._blacklist),
        }


# Convenience functions for integration
async def create_mesh_node(
    role: str = "WORKER",
    bootstrap_peers: Optional[List[str]] = None,
    max_peers: int = 10
) -> MeshNode:
    """Create and start a mesh node with common configuration."""
    config = MeshConfig(
        role=role,
        bootstrap_peers=bootstrap_peers or [],
        max_peers=max_peers,
    )
    
    node = MeshNode(config)
    await node.start()
    
    return node


if __name__ == "__main__":
    # Simple test
    logging.basicConfig(level=logging.INFO)
    
    async def test():
        node = await create_mesh_node(role="COORDINATOR")
        print(f"Node started: {node.get_listen_addr()}")
        
        try:
            while True:
                await asyncio.sleep(10)
                stats = node.get_stats()
                print(f"Stats: {stats}")
        except KeyboardInterrupt:
            await node.stop()
    
    asyncio.run(test())
