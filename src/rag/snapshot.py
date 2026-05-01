"""P5 Snapshot feature.

Provides functionality to backup the ChromaDB index and manifest.
"""

from __future__ import annotations
import shutil
import datetime
import logging
from pathlib import Path

from rag.config import Config

logger = logging.getLogger("rag.snapshot")

ERR_SECURITY = "[ERR_SECURITY]"

class SnapshotError(Exception):
    """Raised on snapshot failures."""

class SnapshotManager:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.backup_dir = cfg.snapshot.backup_dir
        self.index_dir = cfg.paths.index_dir
        self.manifest_path = cfg.paths.manifest_path

        # Basic path safety check for backup_dir
        if self.backup_dir.resolve().is_relative_to(self.cfg.paths.wiki_root.resolve()):
            raise SnapshotError(f"{ERR_SECURITY} Snapshot backup_dir cannot be inside wiki_root: {self.backup_dir}")
        if self.backup_dir.resolve().is_relative_to(self.index_dir.resolve()):
            raise SnapshotError(f"{ERR_SECURITY} Snapshot backup_dir cannot be inside index_dir: {self.backup_dir}")

    def create_snapshot(self) -> Path:
        """Creates a timestamped snapshot of the index_dir and manifest_path."""
        if not self.cfg.snapshot.enabled:
            logger.info("Snapshotting is disabled in config.")
            return Path("")

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        snapshot_target_dir = self.backup_dir / f"snapshot_{timestamp}"
        snapshot_target_dir.mkdir(parents=True, exist_ok=False)

        try:
            # Copy ChromaDB index directory
            shutil.copytree(self.index_dir, snapshot_target_dir / self.index_dir.name)
            # Copy manifest file
            shutil.copy2(self.manifest_path, snapshot_target_dir / self.manifest_path.name)
            logger.info(f"Created snapshot at: {snapshot_target_dir}")
            return snapshot_target_dir
        except Exception as e:
            shutil.rmtree(snapshot_target_dir, ignore_errors=True)
            raise SnapshotError(f"Failed to create snapshot: {e}") from e