"""
Music App Backend — Playlist browser powered by NexusFilesystem
================================================================

Reads playlists and songs from /home/{character}/playlists/ in the
virtual filesystem. Playlists are JSON files created by the
create_playlist skill or the OracleCompanion agent.

Version: v1.51.1 [2026-03-25]
Author:  CosySim Team

Change Log:
    v1.51.1 [2026-03-25] — Initial: list_playlists, get_playlist, now_playing

CONNECTS: engine.nexus.filesystem (NexusFilesystem)
CALLED BY: phone_scene_v2.py routes
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class MusicApp:
    """Music player backend reading playlists from NexusFilesystem."""

    def __init__(self, owner: str = "player"):
        self.owner = owner
        self._now_playing: Optional[Dict[str, Any]] = None
        self._current_playlist: Optional[str] = None
        self._current_index: int = 0

    def _fs(self):
        """Lazy-load filesystem."""
        from engine.nexus.filesystem import get_filesystem
        return get_filesystem(self.owner)

    def _playlists_path(self) -> str:
        return f"/home/{self.owner}/playlists/"

    def list_playlists(self) -> List[Dict[str, Any]]:
        """List all playlists."""
        try:
            fs = self._fs()
            path = self._playlists_path()

            if not fs.exists(path):
                fs.mkdir(path)
                return []

            nodes = fs.list_dir(path)
            playlists = []

            for node in nodes:
                if node.fs_type == "directory":
                    continue
                if not node.name.endswith(".json"):
                    continue

                full_node = fs.read(node.path)
                if full_node and full_node.content:
                    try:
                        data = json.loads(full_node.content)
                        playlists.append({
                            "name": data.get("name", node.name.replace(".json", "")),
                            "description": data.get("description", ""),
                            "mood": data.get("mood", ""),
                            "song_count": data.get("song_count", len(data.get("songs", []))),
                            "created_by": data.get("created_by", "unknown"),
                            "created_at": data.get("created_at", ""),
                            "file": node.name,
                            "path": node.path,
                        })
                    except json.JSONDecodeError:
                        pass

            return playlists

        except Exception as exc:
            logger.error("[MusicApp] List playlists failed (operation=list_playlists): %s", exc)
            return []

    def get_playlist(self, name: str) -> Optional[Dict[str, Any]]:
        """Get a playlist by name (filename without .json)."""
        try:
            fs = self._fs()
            path = f"{self._playlists_path()}{name}.json"

            node = fs.read(path)
            if not node or not node.content:
                return None

            data = json.loads(node.content)
            return {
                "name": data.get("name", name),
                "description": data.get("description", ""),
                "mood": data.get("mood", ""),
                "created_by": data.get("created_by", "unknown"),
                "created_at": data.get("created_at", ""),
                "songs": data.get("songs", []),
                "song_count": len(data.get("songs", [])),
            }

        except Exception as exc:
            logger.error("[MusicApp] Get playlist failed (operation=get_playlist, name=%s): %s", name, exc)
            return None

    def get_now_playing(self) -> Dict[str, Any]:
        """Get current playback state."""
        return {
            "playing": self._now_playing is not None,
            "song": self._now_playing,
            "playlist": self._current_playlist,
            "index": self._current_index,
        }

    def play_playlist(self, name: str, index: int = 0) -> Dict[str, Any]:
        """Start playing a playlist from a specific index."""
        playlist = self.get_playlist(name)
        if not playlist:
            return {"error": f"Playlist '{name}' not found"}

        songs = playlist.get("songs", [])
        if not songs:
            return {"error": "Playlist is empty"}

        idx = min(index, len(songs) - 1)
        self._current_playlist = name
        self._current_index = idx
        self._now_playing = songs[idx]

        return {
            "playing": True,
            "song": self._now_playing,
            "playlist": name,
            "index": idx,
            "total": len(songs),
        }

    def next_song(self) -> Dict[str, Any]:
        """Skip to next song in current playlist."""
        if not self._current_playlist:
            return {"playing": False, "error": "No playlist active"}

        playlist = self.get_playlist(self._current_playlist)
        if not playlist:
            return {"playing": False, "error": "Playlist not found"}

        songs = playlist.get("songs", [])
        self._current_index = (self._current_index + 1) % len(songs)
        self._now_playing = songs[self._current_index]

        return {
            "playing": True,
            "song": self._now_playing,
            "playlist": self._current_playlist,
            "index": self._current_index,
            "total": len(songs),
        }

    def stop(self) -> Dict[str, Any]:
        """Stop playback."""
        self._now_playing = None
        self._current_playlist = None
        self._current_index = 0
        return {"playing": False}

    def playlist_count(self) -> int:
        """Count available playlists."""
        try:
            return len(self.list_playlists())
        except Exception:
            return 0

    def _scan_all_playlists(self) -> List[Dict[str, Any]]:
        """Scan playlists from all known characters (not just owner)."""
        all_playlists = self.list_playlists()

        # Also check /shared/ and /home/oracle/ for shared playlists
        try:
            fs = self._fs()
            for extra_path in ["/shared/playlists/", "/home/oracle/playlists/"]:
                if fs.exists(extra_path):
                    nodes = fs.list_dir(extra_path)
                    for node in nodes:
                        if node.name.endswith(".json"):
                            full_node = fs.read(node.path)
                            if full_node and full_node.content:
                                try:
                                    data = json.loads(full_node.content)
                                    all_playlists.append({
                                        "name": data.get("name", node.name.replace(".json", "")),
                                        "mood": data.get("mood", ""),
                                        "song_count": len(data.get("songs", [])),
                                        "created_by": data.get("created_by", ""),
                                        "path": node.path,
                                        "source": extra_path.split("/")[2] if len(extra_path.split("/")) > 2 else "shared",
                                    })
                                except json.JSONDecodeError:
                                    pass
        except Exception:
            pass

        return all_playlists
