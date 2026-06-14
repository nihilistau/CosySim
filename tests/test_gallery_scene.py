"""Tests for GalleryScene — THE OBSCURA Dark Renaissance Gallery.
=================================================================

Covers:
- SCENE_METADATA structure validation
- Class import verification
- Route registration (GET /api/state, GET /api/exhibitions,
  POST /api/exhibition/set, GET /api/artworks, POST /api/artwork/add,
  GET /api/characters, POST /api/character/move, GET /api/log,
  GET /api/gallery/pieces, GET /api/gallery/piece/<id>)
- Gallery state management (artworks, characters, exhibitions)
- Art data constants

Version: v1.49.5 [2026-03-22]
Author:  CosySim Team

Change Log:
    v1.49.5 [2026-03-22] — Initial test suite for GalleryScene
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest


# ──── Fixtures ────────────────────────────────────────────────────────


def _make_mock_db() -> MagicMock:
    """Build a mock Database with sensible defaults.

    Returns:
        Configured MagicMock mimicking Database.
    """
    db = MagicMock()
    db.get_all_characters.return_value = [
        {"id": "char-001", "name": "Lola", "personality": "Sarcastic"},
        {"id": "char-002", "name": "Viktor", "personality": "Brooding"},
    ]
    db.get_character.return_value = {"id": "char-001", "name": "Lola"}
    return db


# v1.49.5 [2026-03-22] — Central fixture: mock all external deps, build test client
# CONNECTS: Database, MCPFramework, SceneStateManager, TagRegistry
@pytest.fixture()
def gallery_client():
    """Create a GalleryScene with all external dependencies mocked
    and return (test_client, scene).
    """
    mock_db = _make_mock_db()
    with patch("content.scenes.gallery.gallery_scene.Database", return_value=mock_db), \
         patch("content.scenes.gallery.gallery_scene.get_framework", return_value=MagicMock()), \
         patch("content.scenes.gallery.gallery_scene.get_scene_state_manager", return_value=MagicMock()), \
         patch("content.scenes.gallery.gallery_scene.TagRegistry") as mock_tr, \
         patch("content.scenes.gallery.gallery_scene.register_gallery_rules"), \
         patch("content.scenes.gallery.gallery_scene.register_shared_assets"):
        mock_tr.get.return_value = MagicMock()

        from content.scenes.gallery.gallery_scene import GalleryScene
        scene = GalleryScene(port=19004)
        scene.app.config["TESTING"] = True
        client = scene.app.test_client()
        yield client, scene, mock_db


# ──── Metadata ────────────────────────────────────────────────────────


class TestGalleryMetadata:
    """SCENE_METADATA structure validation."""

    def test_scene_metadata_has_required_fields(self):
        with patch("content.scenes.gallery.gallery_scene.Database", return_value=_make_mock_db()), \
             patch("content.scenes.gallery.gallery_scene.get_framework", return_value=MagicMock()), \
             patch("content.scenes.gallery.gallery_scene.get_scene_state_manager", return_value=MagicMock()), \
             patch("content.scenes.gallery.gallery_scene.TagRegistry") as mock_tr, \
             patch("content.scenes.gallery.gallery_scene.register_gallery_rules"), \
             patch("content.scenes.gallery.gallery_scene.register_shared_assets"):
            mock_tr.get.return_value = MagicMock()
            from content.scenes.gallery.gallery_scene import GalleryScene
            meta = GalleryScene.SCENE_METADATA
            assert meta["name"] == "gallery"
            assert meta["display_name"] == "THE OBSCURA"
            assert meta["port"] == 5560
            assert meta["accent_color"] == "#7c3aed"
            assert "description" in meta

    def test_metadata_features_include_image_generation(self):
        with patch("content.scenes.gallery.gallery_scene.Database", return_value=_make_mock_db()), \
             patch("content.scenes.gallery.gallery_scene.get_framework", return_value=MagicMock()), \
             patch("content.scenes.gallery.gallery_scene.get_scene_state_manager", return_value=MagicMock()), \
             patch("content.scenes.gallery.gallery_scene.TagRegistry") as mock_tr, \
             patch("content.scenes.gallery.gallery_scene.register_gallery_rules"), \
             patch("content.scenes.gallery.gallery_scene.register_shared_assets"):
            mock_tr.get.return_value = MagicMock()
            from content.scenes.gallery.gallery_scene import GalleryScene
            features = GalleryScene.SCENE_METADATA["features"]
            assert "image_generation" in features
            assert "economy" in features


# ──── Import ──────────────────────────────────────────────────────────


class TestGalleryImport:
    """Verify the class and constants are importable."""

    def test_class_importable(self):
        from content.scenes.gallery.gallery_scene import GalleryScene
        assert GalleryScene is not None

    def test_scene_id_constant(self):
        from content.scenes.gallery.gallery_scene import SCENE_ID
        assert SCENE_ID == "gallery"

    def test_art_styles_importable(self):
        from content.scenes.gallery.gallery_scene import ART_STYLES
        assert isinstance(ART_STYLES, list)
        assert "cyberpunk" in ART_STYLES
        assert "renaissance" in ART_STYLES

    def test_gallery_rooms_importable(self):
        from content.scenes.gallery.gallery_scene import GALLERY_ROOMS
        assert isinstance(GALLERY_ROOMS, dict)
        assert "main_hall" in GALLERY_ROOMS
        assert "private_collection" in GALLERY_ROOMS

    def test_obscura_pieces_importable(self):
        from content.scenes.gallery.gallery_scene import OBSCURA_PIECES
        assert isinstance(OBSCURA_PIECES, list)
        assert len(OBSCURA_PIECES) >= 8


# ──── State Route ─────────────────────────────────────────────────────


class TestGalleryStateRoute:
    """GET /api/state — gallery state snapshot."""

    def test_state_returns_200(self, gallery_client):
        client, _, _ = gallery_client
        resp = client.get("/api/state")
        assert resp.status_code == 200

    def test_state_has_ok_field(self, gallery_client):
        client, _, _ = gallery_client
        data = client.get("/api/state").get_json()
        assert data["ok"] is True


# ──── Exhibition Routes ───────────────────────────────────────────────


class TestGalleryExhibitions:
    """Exhibition listing and setting."""

    def test_list_exhibitions_returns_200(self, gallery_client):
        client, _, _ = gallery_client
        resp = client.get("/api/exhibitions")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert "exhibitions" in data

    def test_list_exhibitions_contains_premade(self, gallery_client):
        client, _, _ = gallery_client
        data = client.get("/api/exhibitions").get_json()
        exhibitions = data["exhibitions"]
        assert "dreams_unveiled" in exhibitions
        assert "neon_futures" in exhibitions

    def test_set_exhibition_valid(self, gallery_client):
        client, scene, _ = gallery_client
        resp = client.post("/api/exhibition/set", json={"exhibition": "neon_futures"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert scene.active_exhibition == "neon_futures"

    def test_set_exhibition_invalid_returns_400(self, gallery_client):
        client, _, _ = gallery_client
        resp = client.post("/api/exhibition/set", json={"exhibition": "nonexistent"})
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["ok"] is False


# ──── Artwork Routes ──────────────────────────────────────────────────


class TestGalleryArtworks:
    """Artwork listing and adding."""

    def test_list_artworks_returns_200(self, gallery_client):
        client, _, _ = gallery_client
        resp = client.get("/api/artworks")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert "artworks" in data

    def test_add_artwork_creates_entry(self, gallery_client):
        client, scene, _ = gallery_client
        resp = client.post("/api/artwork/add", json={
            "title": "Neon Dreams",
            "style": "cyberpunk",
            "description": "A city that never sleeps.",
            "room": "modern_wing",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["artwork"]["title"] == "Neon Dreams"
        # Verify artwork was stored in scene state
        assert len(scene.artworks) >= 1


# ──── Character Routes ────────────────────────────────────────────────


class TestGalleryCharacters:
    """Character listing and movement."""

    def test_list_characters_returns_200(self, gallery_client):
        client, _, _ = gallery_client
        resp = client.get("/api/characters")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert "characters" in data

    def test_move_character_invalid_returns_400(self, gallery_client):
        """Moving to a nonexistent room should fail."""
        client, _, _ = gallery_client
        resp = client.post("/api/character/move", json={
            "character_id": "char-001",
            "room": "nonexistent_room",
        })
        assert resp.status_code == 400


# ──── Gallery Log ─────────────────────────────────────────────────────


class TestGalleryLog:
    """GET /api/log — gallery event log."""

    def test_log_returns_200(self, gallery_client):
        client, _, _ = gallery_client
        resp = client.get("/api/log")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert "log" in data
        assert isinstance(data["log"], list)


# ──── Gallery Pieces (OBSCURA) ────────────────────────────────────────


class TestGalleryPieces:
    """GET /api/gallery/pieces — permanent collection."""

    def test_pieces_returns_200(self, gallery_client):
        client, _, _ = gallery_client
        resp = client.get("/api/gallery/pieces")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert "pieces" in data
        assert "curator_mood" in data

    def test_piece_detail_not_found(self, gallery_client):
        """Requesting a nonexistent piece returns 404."""
        client, _, _ = gallery_client
        resp = client.get("/api/gallery/piece/nonexistent")
        assert resp.status_code == 404
