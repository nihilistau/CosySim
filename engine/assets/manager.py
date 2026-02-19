"""
Asset Manager - Unified CRUD for all asset types

Provides centralized management of all assets with:
- Create, Read, Update, Delete operations
- Asset registry and indexing
- Dependency tracking
- Versioning support
- Orphan detection
- Batch operations

Example:
    from engine.assets import AssetManager, AudioAsset
    
    manager = AssetManager()
    
    # Create and save asset
    audio = AudioAsset.create(filepath="voice.wav")
    manager.save(audio)
    
    # Load asset
    loaded = manager.load("audio", audio.id)
    
    # Search assets
    results = manager.search(asset_type="audio", tags=["character1"])
    
    # Delete with cascade
    manager.delete(audio.id, cascade=True)
"""

import sqlite3
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from datetime import datetime
import logging

from .base import (
    BaseAsset,
    AssetMetadata,
    AssetDependency,
    AssetValidationError,
    AssetNotFoundError,
    get_asset_class
)

logger = logging.getLogger(__name__)


class AssetManager:
    """Unified asset management system."""
    
    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize asset manager.
        
        Args:
            db_path: Path to asset registry database
        """
        self.db_path = db_path or "asset_registry.db"
        self._init_database()
    
    def _init_database(self) -> None:
        """Initialize asset registry database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Assets table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS assets (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                data TEXT NOT NULL,
                metadata TEXT NOT NULL,
                checksum TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                version INTEGER DEFAULT 1
            )
        """)
        
        # Tags table (many-to-many)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS asset_tags (
                asset_id TEXT NOT NULL,
                tag TEXT NOT NULL,
                PRIMARY KEY (asset_id, tag),
                FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE CASCADE
            )
        """)
        
        # Dependencies table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS asset_dependencies (
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                dependency_type TEXT NOT NULL,
                PRIMARY KEY (source_id, target_id),
                FOREIGN KEY (source_id) REFERENCES assets(id) ON DELETE CASCADE,
                FOREIGN KEY (target_id) REFERENCES assets(id) ON DELETE CASCADE
            )
        """)
        
        # Version history table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS asset_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                data TEXT NOT NULL,
                metadata TEXT NOT NULL,
                checksum TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE CASCADE
            )
        """)
        
        # Indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_asset_type ON assets(type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_asset_tags ON asset_tags(tag)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_dependencies_source ON asset_dependencies(source_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_dependencies_target ON asset_dependencies(target_id)")
        
        conn.commit()
        conn.close()
        
        logger.info(f"Asset registry initialized: {self.db_path}")
    
    def save(
        self,
        asset: BaseAsset,
        create_version: bool = True
    ) -> str:
        """
        Save asset to registry.
        
        Args:
            asset: Asset to save
            create_version: Whether to create version history entry
        
        Returns:
            Asset ID
        
        Raises:
            AssetValidationError: If asset validation fails
        """
        # Validate asset
        if not asset.validate():
            raise AssetValidationError(f"Asset validation failed: {asset.id}")
        
        # Calculate checksum
        checksum = asset.get_checksum()
        
        # Export asset data
        data = json.dumps(asset.export())
        metadata = json.dumps(asset.metadata.to_dict())
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # Check if asset exists
            cursor.execute("SELECT version FROM assets WHERE id = ?", (asset.id,))
            existing = cursor.fetchone()
            
            if existing:
                # Update existing asset
                new_version = existing[0] + 1
                asset.metadata.version = new_version
                asset.metadata.updated_at = datetime.now().isoformat()
                
                # Create version history if enabled
                if create_version:
                    cursor.execute("""
                        INSERT INTO asset_versions (asset_id, version, data, metadata, checksum, created_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (asset.id, existing[0], data, metadata, checksum, asset.metadata.updated_at))
                
                # Update asset
                cursor.execute("""
                    UPDATE assets 
                    SET data = ?, metadata = ?, checksum = ?, updated_at = ?, version = ?
                    WHERE id = ?
                """, (data, metadata, checksum, asset.metadata.updated_at, new_version, asset.id))
                
                logger.info(f"Updated asset: {asset.id} (v{new_version})")
                
            else:
                # Insert new asset
                cursor.execute("""
                    INSERT INTO assets (id, type, data, metadata, checksum, created_at, updated_at, version)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    asset.id,
                    asset.ASSET_TYPE,
                    data,
                    metadata,
                    checksum,
                    asset.metadata.created_at,
                    asset.metadata.updated_at,
                    asset.metadata.version
                ))
                
                logger.info(f"Created asset: {asset.id}")
            
            # Update tags
            cursor.execute("DELETE FROM asset_tags WHERE asset_id = ?", (asset.id,))
            for tag in asset.metadata.tags:
                cursor.execute(
                    "INSERT INTO asset_tags (asset_id, tag) VALUES (?, ?)",
                    (asset.id, tag)
                )
            
            conn.commit()
            return asset.id
            
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to save asset {asset.id}: {e}")
            raise
        finally:
            conn.close()
    
    def load(
        self,
        asset_type: str,
        asset_id: str,
        version: Optional[int] = None
    ) -> BaseAsset:
        """
        Load asset from registry.
        
        Args:
            asset_type: Asset type
            asset_id: Asset ID
            version: Specific version to load (None for latest)
        
        Returns:
            Loaded asset
        
        Raises:
            AssetNotFoundError: If asset not found
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            if version is None:
                # Load latest version
                cursor.execute(
                    "SELECT data, metadata FROM assets WHERE id = ? AND type = ?",
                    (asset_id, asset_type)
                )
            else:
                # Load specific version
                cursor.execute("""
                    SELECT data, metadata FROM asset_versions 
                    WHERE asset_id = ? AND version = ?
                """, (asset_id, version))
            
            row = cursor.fetchone()
            
            if not row:
                raise AssetNotFoundError(f"Asset not found: {asset_type}/{asset_id}")
            
            data = json.loads(row[0])
            metadata = AssetMetadata.from_dict(json.loads(row[1]))
            
            # Get asset class and import
            asset_class = get_asset_class(asset_type)
            asset = asset_class.import_data(data)
            asset.metadata = metadata
            
            logger.debug(f"Loaded asset: {asset_id} (v{metadata.version})")
            
            return asset
            
        finally:
            conn.close()
    
    def delete(
        self,
        asset_id: str,
        cascade: bool = False
    ) -> None:
        """
        Delete asset from registry.
        
        Args:
            asset_id: Asset ID to delete
            cascade: If True, delete dependent assets as well
        
        Raises:
            AssetNotFoundError: If asset not found
            ValueError: If asset has dependencies and cascade=False
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # Check if asset exists
            cursor.execute("SELECT id FROM assets WHERE id = ?", (asset_id,))
            if not cursor.fetchone():
                raise AssetNotFoundError(f"Asset not found: {asset_id}")
            
            # Check for dependencies
            cursor.execute(
                "SELECT source_id FROM asset_dependencies WHERE target_id = ?",
                (asset_id,)
            )
            dependents = [row[0] for row in cursor.fetchall()]
            
            if dependents and not cascade:
                raise ValueError(
                    f"Asset {asset_id} has dependencies: {dependents}. "
                    f"Use cascade=True to delete them as well."
                )
            
            # Delete dependents if cascade
            if cascade:
                for dependent_id in dependents:
                    self.delete(dependent_id, cascade=True)
            
            # Delete asset dependencies
            cursor.execute("DELETE FROM asset_dependencies WHERE source_id = ? OR target_id = ?", 
                         (asset_id, asset_id))
            
            # Delete asset tags
            cursor.execute("DELETE FROM asset_tags WHERE asset_id = ?", (asset_id,))
            
            # Delete asset
            cursor.execute("DELETE FROM assets WHERE id = ?", (asset_id,))
            conn.commit()
            
            logger.info(f"Deleted asset: {asset_id}")
            
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to delete asset {asset_id}: {e}")
            raise
        finally:
            conn.close()
    
    def search(
        self,
        asset_type: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Search for assets.
        
        Args:
            asset_type: Filter by asset type
            tags: Filter by tags (assets must have all tags)
            limit: Maximum results to return
            offset: Offset for pagination
        
        Returns:
            List of asset metadata dictionaries
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # Build query
            query = "SELECT DISTINCT a.id, a.type, a.metadata FROM assets a"
            conditions = []
            params = []
            
            if tags:
                query += " JOIN asset_tags t ON a.id = t.asset_id"
                if asset_type:
                    query += " WHERE a.type = ?"
                    params.append(asset_type)
                
                tag_condition = f"t.tag IN ({','.join('?' * len(tags))})"
                query += (" AND " if asset_type else " WHERE ") + tag_condition
                params.extend(tags)
                query += f" GROUP BY a.id HAVING COUNT(DISTINCT t.tag) = {len(tags)}"
            else:
                if asset_type:
                    query += " WHERE a.type = ?"
                    params.append(asset_type)
            
            query += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            
            cursor.execute(query, params)
            
            results = []
            for row in cursor.fetchall():
                results.append({
                    "id": row[0],
                    "type": row[1],
                    "metadata": json.loads(row[2])
                })
            
            return results
            
        finally:
            conn.close()
    
    def add_dependency(
        self,
        source_id: str,
        target_id: str,
        dependency_type: str = "requires"
    ) -> None:
        """
        Add dependency between assets.
        
        Args:
            source_id: Source asset ID
            target_id: Target asset ID
            dependency_type: Type of dependency
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT OR REPLACE INTO asset_dependencies (source_id, target_id, dependency_type)
                VALUES (?, ?, ?)
            """, (source_id, target_id, dependency_type))
            
            conn.commit()
            logger.debug(f"Added dependency: {source_id} -> {target_id} ({dependency_type})")
            
        finally:
            conn.close()
    
    def get_dependencies(
        self,
        asset_id: str,
        recursive: bool = False
    ) -> List[str]:
        """
        Get asset dependencies.
        
        Args:
            asset_id: Asset ID
            recursive: If True, get all transitive dependencies
        
        Returns:
            List of dependent asset IDs
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            if not recursive:
                cursor.execute(
                    "SELECT target_id FROM asset_dependencies WHERE source_id = ?",
                    (asset_id,)
                )
                return [row[0] for row in cursor.fetchall()]
            
            # Recursive dependency resolution
            visited: Set[str] = set()
            to_visit = [asset_id]
            
            while to_visit:
                current = to_visit.pop(0)
                if current in visited:
                    continue
                
                visited.add(current)
                
                cursor.execute(
                    "SELECT target_id FROM asset_dependencies WHERE source_id = ?",
                    (current,)
                )
                
                for row in cursor.fetchall():
                    if row[0] not in visited:
                        to_visit.append(row[0])
            
            visited.remove(asset_id)  # Remove self
            return list(visited)
            
        finally:
            conn.close()
    
    def find_orphans(self, asset_type: Optional[str] = None) -> List[str]:
        """
        Find orphaned assets (assets with no dependencies pointing to them).
        
        Args:
            asset_type: Filter by asset type
        
        Returns:
            List of orphaned asset IDs
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            query = """
                SELECT a.id FROM assets a
                WHERE a.id NOT IN (
                    SELECT DISTINCT target_id FROM asset_dependencies
                )
            """
            
            params = []
            if asset_type:
                query += " AND a.type = ?"
                params.append(asset_type)
            
            cursor.execute(query, params)
            return [row[0] for row in cursor.fetchall()]
            
        finally:
            conn.close()
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get asset registry statistics.
        
        Returns:
            Dictionary with statistics
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            stats = {}
            
            # Total assets
            cursor.execute("SELECT COUNT(*) FROM assets")
            stats["total_assets"] = cursor.fetchone()[0]
            
            # Assets by type
            cursor.execute("SELECT type, COUNT(*) FROM assets GROUP BY type")
            stats["by_type"] = dict(cursor.fetchall())
            
            # Total tags
            cursor.execute("SELECT COUNT(DISTINCT tag) FROM asset_tags")
            stats["total_tags"] = cursor.fetchone()[0]
            
            # Total dependencies
            cursor.execute("SELECT COUNT(*) FROM asset_dependencies")
            stats["total_dependencies"] = cursor.fetchone()[0]
            
            # Total versions
            cursor.execute("SELECT COUNT(*) FROM asset_versions")
            stats["total_versions"] = cursor.fetchone()[0]
            
            return stats
            
        finally:
            conn.close()
