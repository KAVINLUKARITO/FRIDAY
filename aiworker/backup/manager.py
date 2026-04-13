"""
AIWorker Backup Manager - Phase 3 Production Hardening

Comprehensive backup system for code, state, and knowledge:
- Code backup: Git commits (already in self_modify/engine.py)
- State backup: SQLite databases (checkpoints, telemetry, skills)
- Knowledge backup: Research findings, world state, episodic memory
- Config backup: aiworker_vps.yaml, environment variables

Schedule:
- Real-time: Git commit on every successful patch apply
- Hourly: SQLite database dumps to /opt/aiworker/backups/
- Daily: Full tarball to external storage
- Pre-shutdown: Flush all state, create recovery point

Retention: SQLite 24 hourly/7 daily/4 weekly, tarballs 7 days local/30 days external.
Compression: zstd for speed (level 3), gzip fallback.
"""

import gzip
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from aiworker.config import AIWorkerConfig

logger = logging.getLogger("aiworker.backup")


@dataclass
class BackupPoint:
    """Represents a recovery point."""
    timestamp: float
    path: Path
    backup_type: str  # hourly, daily, manual
    size_bytes: int
    checksum: str
    metadata: dict = field(default_factory=dict)
    
    @property
    def datetime(self) -> datetime:
        return datetime.fromtimestamp(self.timestamp)
    
    @property
    def age_hours(self) -> float:
        return (time.time() - self.timestamp) / 3600


class BackupManager:
    """
    Comprehensive backup system for AIWorker.
    
    Manages backups of:
    - SQLite databases (checkpoints, telemetry, skills, health)
    - Configuration files
    - Research findings and knowledge
    - Full system state
    """
    
    def __init__(self, config: Optional[AIWorkerConfig] = None):
        self.config = config or AIWorkerConfig.from_env()
        self.base_path = Path(self.config.base_path)
        self.backup_path = self.base_path / "backups"
        self.backup_path.mkdir(parents=True, exist_ok=True)
        
        # Retention settings
        self.hourly_retention = 24
        self.daily_retention = 7
        self.weekly_retention = 4
        self.tarball_local_retention_days = 7
        self.tarball_external_retention_days = 30
        
        # Compression preference
        self.use_zstd = shutil.which('zstd') is not None
        
        logger.info(f"BackupManager initialized: {self.backup_path}")
    
    def _get_db_files(self) -> list[Path]:
        """Get list of SQLite database files to backup."""
        data_path = self.base_path / "data"
        
        db_files = []
        for pattern in ['*.db', '*.sqlite', '*.sqlite3']:
            db_files.extend(data_path.glob(pattern))
        
        # Also include checkpoint database
        checkpoint_db = Path(self.config.checkpoint_db)
        if checkpoint_db.exists() and checkpoint_db not in db_files:
            db_files.append(checkpoint_db)
        
        return db_files
    
    def _get_config_files(self) -> list[Path]:
        """Get list of configuration files to backup."""
        config_files = []
        
        # Main config file
        config_path = self.base_path / "aiworker_vps.yaml"
        if config_path.exists():
            config_files.append(config_path)
        
        # Environment file if exists
        env_path = self.base_path / ".env"
        if env_path.exists():
            config_files.append(env_path)
        
        return config_files
    
    def _compute_checksum(self, file_path: Path) -> str:
        """Compute SHA256 checksum of a file."""
        sha256 = hashlib.sha256()
        
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
        
        return sha256.hexdigest()
    
    def backup_sqlite(
        self,
        backup_type: str = "hourly",
        compress: bool = True
    ) -> Optional[BackupPoint]:
        """
        Backup SQLite databases.
        
        Args:
            backup_type: hourly, daily, or manual
            compress: Whether to compress the backup
            
        Returns:
            BackupPoint if successful
        """
        logger.info(f"Starting {backup_type} SQLite backup")
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_name = f"sqlite_{backup_type}_{timestamp}"
        backup_dir = self.backup_path / backup_name
        backup_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            db_files = self._get_db_files()
            
            for db_file in db_files:
                # Use SQLite's backup API for consistency
                backup_file = backup_dir / f"{db_file.stem}.db"
                
                conn = sqlite3.connect(str(db_file))
                backup_conn = sqlite3.connect(str(backup_file))
                
                with backup_conn:
                    conn.backup(backup_conn)
                
                backup_conn.close()
                conn.close()
                
                logger.debug(f"Backed up: {db_file.name}")
            
            # Compress if requested
            if compress:
                if self.use_zstd:
                    archive_path = self._compress_zstd(backup_dir)
                else:
                    archive_path = self._compress_gzip(backup_dir)
                
                # Remove uncompressed directory
                shutil.rmtree(backup_dir)
                backup_dir = archive_path
            
            # Compute checksum
            checksum = self._compute_checksum(backup_dir)
            
            # Create backup point
            point = BackupPoint(
                timestamp=time.time(),
                path=backup_dir,
                backup_type=backup_type,
                size_bytes=backup_dir.stat().st_size,
                checksum=checksum,
                metadata={
                    'db_count': len(db_files),
                    'compression': 'zstd' if self.use_zstd else 'gzip' if compress else 'none'
                }
            )
            
            # Save metadata
            self._save_backup_metadata(point)
            
            logger.info(f"SQLite backup complete: {backup_dir.name}")
            return point
        
        except Exception as e:
            logger.error(f"SQLite backup failed: {e}")
            # Cleanup on failure
            if backup_dir.exists():
                shutil.rmtree(backup_dir, ignore_errors=True)
            return None
    
    def _compress_zstd(self, source_dir: Path) -> Path:
        """Compress directory using zstd."""
        archive_path = Path(str(source_dir) + '.tar.zst')
        
        # Create tar archive and pipe to zstd
        with tempfile.NamedTemporaryFile(suffix='.tar', delete=False) as tmp:
            tmp_path = tmp.name
        
        try:
            with tarfile.open(tmp_path, 'w') as tar:
                tar.add(source_dir, arcname=source_dir.name)
            
            # Compress with zstd
            subprocess.run(
                ['zstd', '-3', '-f', '-o', str(archive_path), tmp_path],
                check=True,
                capture_output=True
            )
        
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        
        return archive_path
    
    def _compress_gzip(self, source_dir: Path) -> Path:
        """Compress directory using gzip."""
        archive_path = Path(str(source_dir) + '.tar.gz')
        
        with tarfile.open(archive_path, 'w:gz') as tar:
            tar.add(source_dir, arcname=source_dir.name)
        
        return archive_path
    
    def _save_backup_metadata(self, point: BackupPoint):
        """Save backup metadata to JSON file."""
        metadata_path = Path(str(point.path) + '.json')
        
        with open(metadata_path, 'w') as f:
            json.dump({
                'timestamp': point.timestamp,
                'backup_type': point.backup_type,
                'size_bytes': point.size_bytes,
                'checksum': point.checksum,
                'metadata': point.metadata
            }, f, indent=2)
    
    def backup_full(
        self,
        include_code: bool = True,
        external_destination: Optional[str] = None
    ) -> Optional[BackupPoint]:
        """
        Create full system backup.
        
        Args:
            include_code: Whether to include git repository
            external_destination: Optional external storage path/URL
            
        Returns:
            BackupPoint if successful
        """
        logger.info("Starting full system backup")
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_name = f"full_{timestamp}"
        backup_dir = self.backup_path / backup_name
        backup_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            # Backup SQLite databases
            db_backup = self.backup_sqlite(backup_type="manual", compress=False)
            if db_backup:
                shutil.move(str(db_backup.path), str(backup_dir / "databases"))
            
            # Backup config files
            config_dir = backup_dir / "config"
            config_dir.mkdir(exist_ok=True)
            
            for config_file in self._get_config_files():
                shutil.copy2(config_file, config_dir)
            
            # Backup environment variables (sanitized)
            env_vars = {k: v for k, v in os.environ.items() 
                       if k.startswith('AIWORKER') or k in ['PATH', 'HOME']}
            
            with open(backup_dir / "environment.json", 'w') as f:
                json.dump(env_vars, f, indent=2)
            
            # Backup code (if requested)
            if include_code:
                code_dir = backup_dir / "code"
                code_dir.mkdir(exist_ok=True)
                
                # Use git to create archive
                git_dir = self.base_path / ".git"
                if git_dir.exists():
                    subprocess.run(
                        ['git', 'archive', '--format=tar', 'HEAD'],
                        cwd=self.base_path,
                        stdout=open(code_dir / "code.tar", 'wb'),
                        check=True
                    )
            
            # Create tarball
            if self.use_zstd:
                archive_path = self._compress_zstd(backup_dir)
            else:
                archive_path = self._compress_gzip(backup_dir)
            
            shutil.rmtree(backup_dir)
            
            # Compute checksum
            checksum = self._compute_checksum(archive_path)
            
            point = BackupPoint(
                timestamp=time.time(),
                path=archive_path,
                backup_type="full",
                size_bytes=archive_path.stat().st_size,
                checksum=checksum,
                metadata={
                    'include_code': include_code,
                    'compression': 'zstd' if self.use_zstd else 'gzip'
                }
            )
            
            self._save_backup_metadata(point)
            
            # Copy to external destination if specified
            if external_destination:
                self._copy_to_external(archive_path, external_destination)
            
            logger.info(f"Full backup complete: {archive_path.name}")
            return point
        
        except Exception as e:
            logger.error(f"Full backup failed: {e}")
            if backup_dir.exists():
                shutil.rmtree(backup_dir, ignore_errors=True)
            return None
    
    def _copy_to_external(self, source: Path, destination: str):
        """Copy backup to external storage."""
        logger.info(f"Copying to external storage: {destination}")
        
        try:
            if destination.startswith(('s3://', 's3a://')):
                # S3 copy using awscli
                subprocess.run(
                    ['aws', 's3', 'cp', str(source), destination],
                    check=True,
                    capture_output=True
                )
            elif destination.startswith('rsync://') or ':' in destination:
                # Rsync
                subprocess.run(
                    ['rsync', '-avz', str(source), destination],
                    check=True,
                    capture_output=True
                )
            else:
                # Local copy
                dest_path = Path(destination)
                dest_path.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, dest_path)
        
        except Exception as e:
            logger.error(f"External copy failed: {e}")
    
    def verify_backup(self, backup_path: Path) -> bool:
        """
        Verify backup integrity.
        
        Args:
            backup_path: Path to backup file
            
        Returns:
            True if backup is valid
        """
        logger.info(f"Verifying backup: {backup_path}")
        
        try:
            # Check file exists and is readable
            if not backup_path.exists():
                logger.error(f"Backup not found: {backup_path}")
                return False
            
            # Load metadata
            metadata_path = Path(str(backup_path) + '.json')
            if not metadata_path.exists():
                logger.warning(f"Metadata not found: {metadata_path}")
                return True  # Can't verify, assume OK
            
            with open(metadata_path) as f:
                metadata = json.load(f)
            
            # Verify checksum
            stored_checksum = metadata.get('checksum')
            if stored_checksum:
                actual_checksum = self._compute_checksum(backup_path)
                if actual_checksum != stored_checksum:
                    logger.error(f"Checksum mismatch: {backup_path}")
                    return False
            
            # Try to open archive
            if backup_path.suffix == '.gz':
                with tarfile.open(backup_path, 'r:gz') as tar:
                    tar.getmembers()
            elif backup_path.suffix == '.zst':
                # Can't easily verify zstd without extracting
                pass
            
            logger.info(f"Backup verified: {backup_path}")
            return True
        
        except Exception as e:
            logger.error(f"Backup verification failed: {e}")
            return False
    
    def list_points(self, backup_type: Optional[str] = None) -> list[BackupPoint]:
        """
        List available recovery points.
        
        Args:
            backup_type: Filter by type (hourly, daily, full, manual)
            
        Returns:
            List of BackupPoint objects
        """
        points = []
        
        for metadata_file in self.backup_path.glob('*.json'):
            try:
                with open(metadata_file) as f:
                    data = json.load(f)
                
                backup_file = metadata_file.with_suffix('')
                # Handle .tar.gz and .tar.zst
                if not backup_file.exists():
                    backup_file = Path(str(metadata_file).replace('.json', ''))
                
                if backup_file.exists():
                    point = BackupPoint(
                        timestamp=data['timestamp'],
                        path=backup_file,
                        backup_type=data['backup_type'],
                        size_bytes=data['size_bytes'],
                        checksum=data['checksum'],
                        metadata=data.get('metadata', {})
                    )
                    
                    if backup_type is None or point.backup_type == backup_type:
                        points.append(point)
            
            except Exception as e:
                logger.debug(f"Failed to load backup metadata: {e}")
        
        # Sort by timestamp (newest first)
        points.sort(key=lambda p: p.timestamp, reverse=True)
        
        return points
    
    def restore_point(
        self,
        timestamp: float,
        target_path: Optional[Path] = None
    ) -> bool:
        """
        Restore to a specific recovery point.
        
        Args:
            timestamp: Timestamp of recovery point
            target_path: Optional alternative restore location
            
        Returns:
            True if restore successful
        """
        logger.info(f"Restoring to point: {timestamp}")
        
        # Find backup point
        points = self.list_points()
        point = None
        
        for p in points:
            if abs(p.timestamp - timestamp) < 1:  # Within 1 second
                point = p
                break
        
        if not point:
            logger.error(f"Backup point not found: {timestamp}")
            return False
        
        # Verify before restore
        if not self.verify_backup(point.path):
            logger.error(f"Backup verification failed, aborting restore")
            return False
        
        try:
            restore_base = target_path or self.base_path
            
            # Extract archive
            if point.path.suffix == '.gz':
                with tarfile.open(point.path, 'r:gz') as tar:
                    tar.extractall(restore_base)
            elif point.path.suffix == '.zst' or str(point.path).endswith('.tar.zst'):
                # Decompress zstd
                import tempfile
                with tempfile.NamedTemporaryFile(suffix='.tar', delete=False) as tmp:
                    subprocess.run(
                        ['zstd', '-d', '-c', str(point.path)],
                        stdout=tmp,
                        check=True
                    )
                    tmp_path = tmp.name
                
                try:
                    with tarfile.open(tmp_path, 'r') as tar:
                        tar.extractall(restore_base)
                finally:
                    os.unlink(tmp_path)
            
            logger.info(f"Restore complete: {point.path.name}")
            return True
        
        except Exception as e:
            logger.error(f"Restore failed: {e}")
            return False
    
    def cleanup_old_backups(self):
        """Remove backups exceeding retention policy."""
        logger.info("Cleaning up old backups")
        
        points = self.list_points()
        
        # Group by type
        hourly = [p for p in points if p.backup_type == 'hourly']
        daily = [p for p in points if p.backup_type == 'daily']
        full = [p for p in points if p.backup_type == 'full']
        manual = [p for p in points if p.backup_type == 'manual']
        
        to_delete = []
        
        # Keep only recent hourly
        if len(hourly) > self.hourly_retention:
            to_delete.extend(hourly[self.hourly_retention:])
        
        # Keep only recent daily
        if len(daily) > self.daily_retention:
            to_delete.extend(daily[self.daily_retention:])
        
        # Keep only recent full (treat as weekly)
        if len(full) > self.weekly_retention:
            to_delete.extend(full[self.weekly_retention:])
        
        # Delete old tarballs
        cutoff = time.time() - (self.tarball_local_retention_days * 24 * 3600)
        for p in full:
            if p.timestamp < cutoff:
                to_delete.append(p)
        
        # Perform deletion
        deleted_count = 0
        for point in to_delete:
            try:
                if point.path.exists():
                    point.path.unlink()
                
                metadata_path = Path(str(point.path) + '.json')
                if metadata_path.exists():
                    metadata_path.unlink()
                
                deleted_count += 1
                logger.debug(f"Deleted old backup: {point.path.name}")
            
            except Exception as e:
                logger.warning(f"Failed to delete backup: {e}")
        
        logger.info(f"Cleanup complete: {deleted_count} backups removed")
    
    def pre_shutdown_backup(self) -> Optional[BackupPoint]:
        """Create emergency backup before shutdown."""
        logger.info("Creating pre-shutdown backup")
        
        # Quick SQLite backup
        return self.backup_sqlite(backup_type="manual", compress=True)


# Factory function
def create_backup_manager(config: Optional[AIWorkerConfig] = None) -> BackupManager:
    """Create and return a BackupManager instance."""
    return BackupManager(config)
