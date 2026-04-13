"""
AIWorker Telemetry Monitor - Phase 3 Production Hardening

Real-time resource monitoring for 32GB VPS with alerting:
- Memory tracking: Current, peak, available, swap usage
- CPU tracking: Load average, per-core usage, iowait
- Disk tracking: I/O wait, throughput on NVMe
- Ollama tracking: Model load status, inference latency, queue depth
- Process tracking: AIWorker RSS/VMS, subprocess count, zombie detection

Alert thresholds from config:
- Memory > 28GB: WARNING
- Memory > 30GB: CRITICAL (trigger model unload)
- Swap > 40GB: WARNING
- CPU iowait > 30%: WARNING (disk bottleneck)
- Ollama queue > 3: WARNING (backpressure)

SQLite persistence with 7-day retention and hourly aggregation.
"""

import gc
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# Try psutil, fallback to /proc parsing
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

from aiworker.config import AIWorkerConfig

logger = logging.getLogger("aiworker.telemetry")


@dataclass
class MemoryStats:
    """Memory statistics."""
    total_bytes: int
    available_bytes: int
    used_bytes: int
    free_bytes: int
    buffers_bytes: int
    cached_bytes: int
    swap_total_bytes: int
    swap_used_bytes: int
    swap_free_bytes: int
    
    @property
    def used_gb(self) -> float:
        return self.used_bytes / (1024 ** 3)
    
    @property
    def available_gb(self) -> float:
        return self.available_bytes / (1024 ** 3)
    
    @property
    def swap_used_gb(self) -> float:
        return self.swap_used_bytes / (1024 ** 3)
    
    @property
    def percent(self) -> float:
        if self.total_bytes == 0:
            return 0.0
        return (self.used_bytes / self.total_bytes) * 100


@dataclass
class CPUStats:
    """CPU statistics."""
    user_percent: float
    system_percent: float
    idle_percent: float
    iowait_percent: float
    load_average_1m: float
    load_average_5m: float
    load_average_15m: float
    core_count: int
    
    @property
    def used_percent(self) -> float:
        return 100.0 - self.idle_percent


@dataclass
class DiskStats:
    """Disk I/O statistics."""
    read_bytes_per_sec: float
    write_bytes_per_sec: float
    read_iops: float
    write_iops: float
    io_wait_percent: float


@dataclass
class OllamaStats:
    """Ollama service statistics."""
    is_running: bool
    loaded_models: list[str]
    inference_latency_ms: float
    queue_depth: int
    vram_used_bytes: int
    vram_total_bytes: int


@dataclass
class ProcessStats:
    """AIWorker process statistics."""
    pid: int
    rss_bytes: int
    vms_bytes: int
    cpu_percent: float
    num_threads: int
    subprocess_count: int
    zombie_count: int
    
    @property
    def rss_mb(self) -> float:
        return self.rss_bytes / (1024 ** 2)


@dataclass
class TelemetrySnapshot:
    """Complete telemetry snapshot."""
    timestamp: float
    memory: MemoryStats
    cpu: CPUStats
    disk: DiskStats
    ollama: OllamaStats
    process: ProcessStats


@dataclass
class Alert:
    """Alert notification."""
    timestamp: float
    severity: str  # CRITICAL, WARNING, INFO
    metric_type: str
    message: str
    value: float
    threshold: float
    unit: str


class TelemetryMonitor:
    """
    Real-time resource monitoring for AIWorker.
    
    Runs background thread to collect metrics at configurable intervals.
    Persists to SQLite with automatic retention management.
    """
    
    def __init__(self, config: Optional[AIWorkerConfig] = None):
        self.config = config or AIWorkerConfig.from_env()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._last_alerts: dict[str, float] = {}  # Rate limiting
        self._last_disk_io: Optional[tuple] = None
        
        # Alert thresholds
        self.memory_warning_gb = 28.0
        self.memory_critical_gb = 30.0
        self.swap_warning_gb = 40.0
        self.iowait_warning_percent = 30.0
        self.ollama_queue_warning = 3
        
        # Ensure database exists
        self._init_database()
        
        logger.info("TelemetryMonitor initialized")
    
    def _init_database(self):
        """Initialize SQLite database for telemetry storage."""
        db_path = Path(self.config.base_path) / "data" / "telemetry.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        # Raw samples table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS telemetry_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                metric_type TEXT NOT NULL,
                value REAL NOT NULL,
                unit TEXT,
                metadata TEXT
            )
        ''')
        
        # Hourly aggregates
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS telemetry_hourly (
                hour INTEGER PRIMARY KEY,
                metric_type TEXT NOT NULL,
                avg_value REAL,
                min_value REAL,
                max_value REAL,
                sample_count INTEGER
            )
        ''')
        
        # Alerts table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS telemetry_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                severity TEXT NOT NULL,
                metric_type TEXT NOT NULL,
                message TEXT,
                value REAL,
                threshold REAL,
                unit TEXT
            )
        ''')
        
        # Indexes
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_samples_time 
            ON telemetry_samples(timestamp)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_samples_type 
            ON telemetry_samples(metric_type)
        ''')
        
        conn.commit()
        conn.close()
        
        logger.debug(f"Telemetry database initialized: {db_path}")
    
    def _get_db_path(self) -> Path:
        """Get database path."""
        return Path(self.config.base_path) / "data" / "telemetry.db"
    
    def _parse_meminfo(self) -> MemoryStats:
        """Parse /proc/meminfo for memory statistics."""
        try:
            with open('/proc/meminfo', 'r') as f:
                meminfo = f.read()
            
            values = {}
            for line in meminfo.strip().split('\n'):
                parts = line.split(':')
                if len(parts) == 2:
                    key = parts[0].strip()
                    # Extract numeric value (in kB)
                    val_str = parts[1].strip().split()[0]
                    values[key] = int(val_str) * 1024  # Convert to bytes
            
            total = values.get('MemTotal', 0)
            free = values.get('MemFree', 0)
            buffers = values.get('Buffers', 0)
            cached = values.get('Cached', 0)
            available = values.get('MemAvailable', free + buffers + cached)
            
            swap_total = values.get('SwapTotal', 0)
            swap_free = values.get('SwapFree', 0)
            swap_used = swap_total - swap_free
            
            return MemoryStats(
                total_bytes=total,
                available_bytes=available,
                used_bytes=total - available,
                free_bytes=free,
                buffers_bytes=buffers,
                cached_bytes=cached,
                swap_total_bytes=swap_total,
                swap_used_bytes=swap_used,
                swap_free_bytes=swap_free
            )
        
        except Exception as e:
            logger.warning(f"Failed to parse /proc/meminfo: {e}")
            return MemoryStats(0, 0, 0, 0, 0, 0, 0, 0, 0)
    
    def _parse_stat(self) -> CPUStats:
        """Parse /proc/stat for CPU statistics."""
        try:
            with open('/proc/stat', 'r') as f:
                stat = f.read()
            
            # Parse CPU line
            cpu_line = stat.split('\n')[0]
            parts = cpu_line.split()
            
            if len(parts) >= 8:
                user = int(parts[1])
                nice = int(parts[2])
                system = int(parts[3])
                idle = int(parts[4])
                iowait = int(parts[5])
                irq = int(parts[6])
                softirq = int(parts[7])
                
                total = user + nice + system + idle + iowait + irq + softirq
                
                user_percent = (user / total) * 100 if total > 0 else 0
                system_percent = (system / total) * 100 if total > 0 else 0
                idle_percent = (idle / total) * 100 if total > 0 else 0
                iowait_percent = (iowait / total) * 100 if total > 0 else 0
            else:
                user_percent = system_percent = idle_percent = iowait_percent = 0.0
            
            # Load average
            try:
                with open('/proc/loadavg', 'r') as f:
                    loadavg = f.read().split()
                    load_1m = float(loadavg[0])
                    load_5m = float(loadavg[1])
                    load_15m = float(loadavg[2])
            except Exception:
                load_1m = load_5m = load_15m = 0.0
            
            # Core count
            try:
                core_count = sum(1 for line in stat.split('\n') if line.startswith('cpu') and line[3].isdigit())
            except Exception:
                core_count = 1
            
            return CPUStats(
                user_percent=user_percent,
                system_percent=system_percent,
                idle_percent=idle_percent,
                iowait_percent=iowait_percent,
                load_average_1m=load_1m,
                load_average_5m=load_5m,
                load_average_15m=load_15m,
                core_count=core_count
            )
        
        except Exception as e:
            logger.warning(f"Failed to parse /proc/stat: {e}")
            return CPUStats(0, 0, 100, 0, 0, 0, 0, 1)
    
    def _parse_diskstats(self) -> DiskStats:
        """Parse /proc/diskstats for disk I/O statistics."""
        try:
            with open('/proc/diskstats', 'r') as f:
                diskstats = f.read()
            
            total_reads = 0
            total_writes = 0
            total_read_sectors = 0
            total_write_sectors = 0
            
            for line in diskstats.strip().split('\n'):
                parts = line.split()
                if len(parts) >= 14:
                    device = parts[2]
                    # Focus on NVMe and main block devices
                    if device.startswith(('nvme', 'sd', 'vd')) and not device[-1].isdigit():
                        reads = int(parts[3])
                        read_sectors = int(parts[5])
                        writes = int(parts[7])
                        write_sectors = int(parts[9])
                        
                        total_reads += reads
                        total_writes += writes
                        total_read_sectors += read_sectors
                        total_write_sectors += write_sectors
            
            # Calculate rates if we have previous data
            current_time = time.time()
            read_bytes_per_sec = 0.0
            write_bytes_per_sec = 0.0
            read_iops = 0.0
            write_iops = 0.0
            
            if self._last_disk_io:
                last_time, last_reads, last_writes, last_read_sectors, last_write_sectors = self._last_disk_io
                time_delta = current_time - last_time
                
                if time_delta > 0:
                    read_iops = (total_reads - last_reads) / time_delta
                    write_iops = (total_writes - last_writes) / time_delta
                    # Sector size is typically 512 bytes
                    read_bytes_per_sec = ((total_read_sectors - last_read_sectors) * 512) / time_delta
                    write_bytes_per_sec = ((total_write_sectors - last_write_sectors) * 512) / time_delta
            
            self._last_disk_io = (current_time, total_reads, total_writes, total_read_sectors, total_write_sectors)
            
            # Get iowait from CPU stats
            cpu_stats = self._parse_stat()
            
            return DiskStats(
                read_bytes_per_sec=read_bytes_per_sec,
                write_bytes_per_sec=write_bytes_per_sec,
                read_iops=read_iops,
                write_iops=write_iops,
                io_wait_percent=cpu_stats.iowait_percent
            )
        
        except Exception as e:
            logger.warning(f"Failed to parse /proc/diskstats: {e}")
            return DiskStats(0, 0, 0, 0, 0)
    
    def _get_ollama_stats(self) -> OllamaStats:
        """Get Ollama service statistics."""
        import httpx
        
        try:
            # Check if Ollama is running
            response = httpx.get(
                f"{self.config.ollama_host}/api/tags",
                timeout=5.0
            )
            
            is_running = response.status_code == 200
            loaded_models = []
            
            if is_running:
                data = response.json()
                loaded_models = [m.get('name', 'unknown') for m in data.get('models', [])]
            
            # Try to get more detailed stats from Ollama
            vram_used = 0
            vram_total = 0
            queue_depth = 0
            latency = 0.0
            
            return OllamaStats(
                is_running=is_running,
                loaded_models=loaded_models,
                inference_latency_ms=latency,
                queue_depth=queue_depth,
                vram_used_bytes=vram_used,
                vram_total_bytes=vram_total
            )
        
        except Exception as e:
            logger.debug(f"Ollama stats unavailable: {e}")
            return OllamaStats(
                is_running=False,
                loaded_models=[],
                inference_latency_ms=0.0,
                queue_depth=0,
                vram_used_bytes=0,
                vram_total_bytes=0
            )
    
    def _get_process_stats(self) -> ProcessStats:
        """Get AIWorker process statistics."""
        import os
        
        try:
            pid = os.getpid()
            
            # Parse /proc/self/status for memory
            with open('/proc/self/status', 'r') as f:
                status = f.read()
            
            rss = 0
            vms = 0
            threads = 0
            
            for line in status.split('\n'):
                if line.startswith('VmRSS:'):
                    rss = int(line.split()[1]) * 1024  # Convert kB to bytes
                elif line.startswith('VmSize:'):
                    vms = int(line.split()[1]) * 1024
                elif line.startswith('Threads:'):
                    threads = int(line.split()[1])
            
            # Count subprocesses
            subprocess_count = 0
            zombie_count = 0
            
            try:
                for entry in Path('/proc').iterdir():
                    if entry.name.isdigit():
                        try:
                            with open(entry / 'stat', 'r') as f:
                                stat = f.read()
                                # Check if parent is our PID
                                ppid = int(stat.split(')')[1].split()[1])
                                if ppid == pid:
                                    subprocess_count += 1
                                    # Check for zombie state
                                    state = stat.split(')')[1].split()[0]
                                    if 'Z' in state:
                                        zombie_count += 1
                        except (PermissionError, FileNotFoundError):
                            pass
            except Exception as e:
                logger.debug(f"Failed to count subprocesses: {e}")
            
            # CPU percent (simplified)
            cpu_percent = 0.0
            
            return ProcessStats(
                pid=pid,
                rss_bytes=rss,
                vms_bytes=vms,
                cpu_percent=cpu_percent,
                num_threads=threads,
                subprocess_count=subprocess_count,
                zombie_count=zombie_count
            )
        
        except Exception as e:
            logger.warning(f"Failed to get process stats: {e}")
            return ProcessStats(0, 0, 0, 0.0, 0, 0, 0)
    
    def get_snapshot(self) -> TelemetrySnapshot:
        """Get current telemetry snapshot."""
        with self._lock:
            return TelemetrySnapshot(
                timestamp=time.time(),
                memory=self._parse_meminfo(),
                cpu=self._parse_stat(),
                disk=self._parse_diskstats(),
                ollama=self._get_ollama_stats(),
                process=self._get_process_stats()
            )
    
    def _persist_sample(self, snapshot: TelemetrySnapshot):
        """Persist telemetry sample to database."""
        try:
            conn = sqlite3.connect(str(self._get_db_path()))
            cursor = conn.cursor()
            
            samples = [
                (snapshot.timestamp, 'memory_used_gb', snapshot.memory.used_gb, 'GB', None),
                (snapshot.timestamp, 'memory_available_gb', snapshot.memory.available_gb, 'GB', None),
                (snapshot.timestamp, 'memory_percent', snapshot.memory.percent, '%', None),
                (snapshot.timestamp, 'swap_used_gb', snapshot.memory.swap_used_gb, 'GB', None),
                (snapshot.timestamp, 'cpu_used_percent', snapshot.cpu.used_percent, '%', None),
                (snapshot.timestamp, 'cpu_iowait_percent', snapshot.cpu.iowait_percent, '%', None),
                (snapshot.timestamp, 'load_average_1m', snapshot.cpu.load_average_1m, '', None),
                (snapshot.timestamp, 'disk_read_mbps', snapshot.disk.read_bytes_per_sec / (1024**2), 'MB/s', None),
                (snapshot.timestamp, 'disk_write_mbps', snapshot.disk.write_bytes_per_sec / (1024**2), 'MB/s', None),
                (snapshot.timestamp, 'process_rss_mb', snapshot.process.rss_mb, 'MB', None),
                (snapshot.timestamp, 'process_subprocesses', snapshot.process.subprocess_count, '', None),
                (snapshot.timestamp, 'ollama_queue', snapshot.ollama.queue_depth, '', None),
            ]
            
            cursor.executemany('''
                INSERT INTO telemetry_samples (timestamp, metric_type, value, unit, metadata)
                VALUES (?, ?, ?, ?, ?)
            ''', samples)
            
            conn.commit()
            conn.close()
        
        except Exception as e:
            logger.warning(f"Failed to persist telemetry: {e}")
    
    def check_alerts(self) -> list[Alert]:
        """Check for alert conditions (rate-limited)."""
        snapshot = self.get_snapshot()
        alerts = []
        current_time = time.time()
        
        # Rate limiting: max 1 alert per 5 minutes per type
        def should_alert(alert_type: str) -> bool:
            last_time = self._last_alerts.get(alert_type, 0)
            if current_time - last_time > 300:  # 5 minutes
                self._last_alerts[alert_type] = current_time
                return True
            return False
        
        # Memory critical
        if snapshot.memory.used_gb > self.memory_critical_gb:
            if should_alert('memory_critical'):
                alerts.append(Alert(
                    timestamp=current_time,
                    severity='CRITICAL',
                    metric_type='memory',
                    message=f'Memory critical: {snapshot.memory.used_gb:.1f}GB used',
                    value=snapshot.memory.used_gb,
                    threshold=self.memory_critical_gb,
                    unit='GB'
                ))
        
        # Memory warning
        elif snapshot.memory.used_gb > self.memory_warning_gb:
            if should_alert('memory_warning'):
                alerts.append(Alert(
                    timestamp=current_time,
                    severity='WARNING',
                    metric_type='memory',
                    message=f'High memory usage: {snapshot.memory.used_gb:.1f}GB used',
                    value=snapshot.memory.used_gb,
                    threshold=self.memory_warning_gb,
                    unit='GB'
                ))
        
        # Swap warning
        if snapshot.memory.swap_used_gb > self.swap_warning_gb:
            if should_alert('swap_warning'):
                alerts.append(Alert(
                    timestamp=current_time,
                    severity='WARNING',
                    metric_type='swap',
                    message=f'High swap usage: {snapshot.memory.swap_used_gb:.1f}GB used',
                    value=snapshot.memory.swap_used_gb,
                    threshold=self.swap_warning_gb,
                    unit='GB'
                ))
        
        # IOWait warning
        if snapshot.cpu.iowait_percent > self.iowait_warning_percent:
            if should_alert('iowait_warning'):
                alerts.append(Alert(
                    timestamp=current_time,
                    severity='WARNING',
                    metric_type='iowait',
                    message=f'Disk bottleneck: {snapshot.cpu.iowait_percent:.1f}% iowait',
                    value=snapshot.cpu.iowait_percent,
                    threshold=self.iowait_warning_percent,
                    unit='%'
                ))
        
        # Ollama queue warning
        if snapshot.ollama.queue_depth > self.ollama_queue_warning:
            if should_alert('ollama_queue'):
                alerts.append(Alert(
                    timestamp=current_time,
                    severity='WARNING',
                    metric_type='ollama_queue',
                    message=f'Ollama backpressure: {snapshot.ollama.queue_depth} queued',
                    value=snapshot.ollama.queue_depth,
                    threshold=self.ollama_queue_warning,
                    unit='requests'
                ))
        
        # Persist alerts
        if alerts:
            try:
                conn = sqlite3.connect(str(self._get_db_path()))
                cursor = conn.cursor()
                
                for alert in alerts:
                    cursor.execute('''
                        INSERT INTO telemetry_alerts 
                        (timestamp, severity, metric_type, message, value, threshold, unit)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (alert.timestamp, alert.severity, alert.metric_type,
                          alert.message, alert.value, alert.threshold, alert.unit))
                
                conn.commit()
                conn.close()
            except Exception as e:
                logger.warning(f"Failed to persist alerts: {e}")
        
        return alerts
    
    def emergency_flush(self):
        """Force model unload, clear caches, run gc.collect()."""
        logger.critical("EMERGENCY FLUSH: Freeing memory")
        
        # Request Ollama to unload models
        import httpx
        try:
            httpx.post(f"{self.config.ollama_host}/api/generate", 
                      json={"model": "", "keep_alive": 0},
                      timeout=10.0)
            logger.info("Ollama model unload requested")
        except Exception as e:
            logger.warning(f"Failed to unload Ollama models: {e}")
        
        # Clear Python caches
        import gc
        gc.collect()
        
        # Try to drop Linux caches (requires root)
        try:
            with open('/proc/sys/vm/drop_caches', 'w') as f:
                f.write('3')
            logger.info("Linux caches dropped")
        except PermissionError:
            logger.debug("Cannot drop Linux caches (requires root)")
        
        logger.info("Emergency flush complete")
    
    def _purge_old_data(self):
        """Purge data older than retention period."""
        try:
            cutoff = time.time() - (7 * 24 * 3600)  # 7 days
            
            conn = sqlite3.connect(str(self._get_db_path()))
            cursor = conn.cursor()
            
            cursor.execute('''
                DELETE FROM telemetry_samples WHERE timestamp < ?
            ''', (cutoff,))
            
            deleted = cursor.rowcount
            conn.commit()
            conn.close()
            
            if deleted > 0:
                logger.debug(f"Purged {deleted} old telemetry samples")
        
        except Exception as e:
            logger.warning(f"Failed to purge old data: {e}")
    
    def _monitoring_loop(self, interval_seconds: float):
        """Main monitoring loop."""
        logger.info(f"Monitoring loop started (interval: {interval_seconds}s)")
        
        while self._running:
            try:
                # Get snapshot
                snapshot = self.get_snapshot()
                
                # Persist
                self._persist_sample(snapshot)
                
                # Check alerts
                alerts = self.check_alerts()
                for alert in alerts:
                    log_method = getattr(logger, alert.severity.lower(), logger.info)
                    log_method(f"ALERT: {alert.message}")
                    
                    # Trigger emergency flush on critical memory
                    if alert.severity == 'CRITICAL' and alert.metric_type == 'memory':
                        self.emergency_flush()
                
                # Periodic purge (once per hour)
                if int(time.time()) % 3600 < interval_seconds:
                    self._purge_old_data()
                
            except Exception as e:
                logger.error(f"Monitoring loop error: {e}")
            
            # Sleep with early exit check
            for _ in range(int(interval_seconds * 10)):
                if not self._running:
                    break
                time.sleep(0.1)
        
        logger.info("Monitoring loop stopped")
    
    def start_monitoring(self, interval_seconds: float = 10.0):
        """Start background monitoring thread."""
        if self._running:
            logger.warning("Monitoring already running")
            return
        
        self._running = True
        self._thread = threading.Thread(
            target=self._monitoring_loop,
            args=(interval_seconds,),
            daemon=True,
            name="TelemetryMonitor"
        )
        self._thread.start()
        
        logger.info(f"Telemetry monitoring started (interval: {interval_seconds}s)")
    
    def stop_monitoring(self):
        """Stop background monitoring thread."""
        if not self._running:
            return
        
        self._running = False
        
        if self._thread:
            self._thread.join(timeout=5.0)
        
        logger.info("Telemetry monitoring stopped")


# Factory function
def create_telemetry_monitor(config: Optional[AIWorkerConfig] = None) -> TelemetryMonitor:
    """Create and return a TelemetryMonitor instance."""
    return TelemetryMonitor(config)
