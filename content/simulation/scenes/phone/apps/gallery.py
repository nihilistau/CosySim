"""
Gallery App - Photo and video gallery
"""

import os
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional


class Gallery:
    """Manage photo and video gallery"""
    
    def __init__(self, db, media_dir: str = None):
        self.db = db
        
        if media_dir is None:
            self.media_dir = Path(__file__).parent.parent.parent.parent / "media"
        else:
            self.media_dir = Path(media_dir)
        
        self.media_dir.mkdir(exist_ok=True)
    
    def add_media(
        self,
        character_id: str,
        filepath: str,
        media_type: str = "image",
        thumbnail: str = None,
        metadata: Dict = None
    ) -> str:
        """
        Add media to gallery
        
        Args:
            character_id: ID of character
            filepath: Path to media file
            media_type: 'image' or 'video'
            thumbnail: Path to thumbnail
            metadata: Additional metadata
        
        Returns:
            Media ID
        """
        # Ensure file exists
        if not Path(filepath).exists():
            raise FileNotFoundError(f"Media file not found: {filepath}")
        
        # Insert into database
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO media (character_id, type, filepath, thumbnail, metadata)
                VALUES (?, ?, ?, ?, ?)
            """, (
                character_id,
                media_type,
                filepath,
                thumbnail,
                str(metadata) if metadata else None
            ))
            conn.commit()
            media_id = cursor.lastrowid
        
        return str(media_id)
    
    def get_media(self, media_id: str) -> Optional[Dict]:
        """Get media by ID"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, character_id, type, filepath, thumbnail, created_at, metadata
                FROM media
                WHERE id = ?
            """, (media_id,))
            
            row = cursor.fetchone()
            if row:
                return {
                    'id': row[0],
                    'character_id': row[1],
                    'type': row[2],
                    'filepath': row[3],
                    'thumbnail': row[4],
                    'created_at': row[5],
                    'metadata': row[6]
                }
        
        return None
    
    def get_character_media(
        self,
        character_id: str,
        media_type: str = None,
        limit: int = 50
    ) -> List[Dict]:
        """
        Get all media for a character
        
        Args:
            character_id: ID of character
            media_type: Filter by type ('image' or 'video')
            limit: Maximum number to return
        
        Returns:
            List of media items
        """
        query = """
            SELECT id, character_id, type, filepath, thumbnail, created_at, metadata
            FROM media
            WHERE character_id = ?
        """
        params = [character_id]
        
        if media_type:
            query += " AND type = ?"
            params.append(media_type)
        
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        
        media_list = []
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            
            for row in cursor.fetchall():
                media_list.append({
                    'id': row[0],
                    'character_id': row[1],
                    'type': row[2],
                    'filepath': row[3],
                    'thumbnail': row[4],
                    'created_at': row[5],
                    'metadata': row[6]
                })
        
        return media_list
    
    def delete_media(self, media_id: str, delete_file: bool = True) -> bool:
        """
        Delete media
        
        Args:
            media_id: ID of media
            delete_file: Whether to delete the physical file
        
        Returns:
            Success status
        """
        # Get media info
        media = self.get_media(media_id)
        if not media:
            return False
        
        # Delete from database
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM media WHERE id = ?", (media_id,))
            conn.commit()
        
        # Delete files if requested
        if delete_file:
            try:
                filepath = Path(media['filepath'])
                if filepath.exists():
                    filepath.unlink()
                
                if media['thumbnail']:
                    thumb_path = Path(media['thumbnail'])
                    if thumb_path.exists():
                        thumb_path.unlink()
            except Exception as e:
                print(f"Error deleting files: {e}")
        
        return True
    
    def get_recent_media(self, limit: int = 20) -> List[Dict]:
        """Get most recent media across all characters"""
        query = """
            SELECT id, character_id, type, filepath, thumbnail, created_at, metadata
            FROM media
            ORDER BY created_at DESC
            LIMIT ?
        """
        
        media_list = []
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, (limit,))
            
            for row in cursor.fetchall():
                media_list.append({
                    'id': row[0],
                    'character_id': row[1],
                    'type': row[2],
                    'filepath': row[3],
                    'thumbnail': row[4],
                    'created_at': row[5],
                    'metadata': row[6]
                })
        
        return media_list
    
    def get_media_count(self, character_id: str = None) -> int:
        """Get count of media items"""
        if character_id:
            query = "SELECT COUNT(*) FROM media WHERE character_id = ?"
            params = (character_id,)
        else:
            query = "SELECT COUNT(*) FROM media"
            params = ()
        
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return cursor.fetchone()[0]
