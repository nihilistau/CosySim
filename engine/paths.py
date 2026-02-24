"""
Centralized path resolution for CosySim.

Every file-system path the project uses should be resolved through this
module.  Keeps directory layout in one place so restructuring only
requires edits here.

Usage:
    from engine.paths import paths
    db = paths.data / "simulation.db"
"""

from pathlib import Path

# ── Project root (one level above engine/) ───────────────────────────
ROOT: Path = Path(__file__).resolve().parent.parent

# ── Top-level directories ────────────────────────────────────────────
CONFIG_DIR: Path   = ROOT / "config"
DATA_DIR: Path     = ROOT / "data"
CONTENT_DIR: Path  = ROOT / "content"
ENGINE_DIR: Path   = ROOT / "engine"
DOCS_DIR: Path     = ROOT / "docs"
TESTS_DIR: Path    = ROOT / "tests"
TRAINING_DIR: Path = ROOT / "training"
DEPLOY_DIR: Path   = ROOT / "deployment"
LOGS_DIR: Path     = ROOT / "logs"

# ── Content sub-trees ────────────────────────────────────────────────
SCENES_DIR: Path      = CONTENT_DIR / "scenes"
CHARACTERS_DIR: Path  = CONTENT_DIR / "characters"
SHARED_DIR: Path      = CONTENT_DIR / "shared"

# ── Media directories ────────────────────────────────────────────────
MEDIA_DIR: Path       = CONTENT_DIR / "simulation" / "media"
IMAGES_DIR: Path      = MEDIA_DIR / "images"
VIDEO_DIR: Path       = MEDIA_DIR / "video"
VOICE_DIR: Path       = MEDIA_DIR / "voice"
PHOTO_DIR: Path       = MEDIA_DIR / "photo"

# Alt media location (content/media/)
MEDIA_ALT_DIR: Path   = CONTENT_DIR / "media"

# ── Asset / voice / model directories ────────────────────────────────
ASSET_DIR: Path           = ROOT / "asset"
VOICES_CONFIG: Path       = CONFIG_DIR / "voices.yaml"
PRETRAINED_MODELS: Path   = ROOT / "pretrained_models"

# ── Database paths (all under data/) ─────────────────────────────────
DB_SIMULATION: Path    = DATA_DIR / "simulation.db"
DB_AGENT_STATE: Path   = DATA_DIR / "agent_state.db"
DB_PHONE: Path         = DATA_DIR / "phone_v2.db"
DB_SHARED_BOARDS: Path = DATA_DIR / "shared_boards.db"
DB_ASSET_REGISTRY: Path = DATA_DIR / "asset_registry.db"
DB_CHROMA_DIR: Path    = DATA_DIR / "chroma_db"
UPLOADS_DIR: Path      = DATA_DIR / "uploads"

# ── Backups ──────────────────────────────────────────────────────────
BACKUPS_DIR: Path = ROOT / "backups"


def ensure_dirs() -> None:
    """Create required directories if they don't exist."""
    for d in (DATA_DIR, IMAGES_DIR, VIDEO_DIR, VOICE_DIR, PHOTO_DIR,
              PHOTO_DIR / "avatars", UPLOADS_DIR, DB_CHROMA_DIR, LOGS_DIR,
              MEDIA_ALT_DIR / "images", MEDIA_ALT_DIR / "video",
              MEDIA_ALT_DIR / "voice", BACKUPS_DIR, DEPLOY_DIR):
        d.mkdir(parents=True, exist_ok=True)


# Convenience alias — immutable namespace
class _Paths:
    """Attribute-style access to all project paths (read-only)."""
    __slots__ = ()  # prevent instance attributes

    root            = ROOT
    config          = CONFIG_DIR
    data            = DATA_DIR
    content         = CONTENT_DIR
    engine          = ENGINE_DIR
    docs            = DOCS_DIR
    tests           = TESTS_DIR
    training        = TRAINING_DIR
    deploy          = DEPLOY_DIR
    logs            = LOGS_DIR
    scenes          = SCENES_DIR
    characters      = CHARACTERS_DIR
    shared          = SHARED_DIR
    media           = MEDIA_DIR
    images          = IMAGES_DIR
    video           = VIDEO_DIR
    voice           = VOICE_DIR
    photo           = PHOTO_DIR
    media_alt       = MEDIA_ALT_DIR
    asset           = ASSET_DIR
    voices_config   = VOICES_CONFIG
    pretrained      = PRETRAINED_MODELS
    db_simulation   = DB_SIMULATION
    db_agent_state  = DB_AGENT_STATE
    db_phone        = DB_PHONE
    db_boards       = DB_SHARED_BOARDS
    db_assets       = DB_ASSET_REGISTRY
    db_chroma       = DB_CHROMA_DIR
    uploads         = UPLOADS_DIR
    backups         = BACKUPS_DIR


paths = _Paths()
