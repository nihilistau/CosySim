"""Media Gallery page — browse generated images, videos, audio."""
import streamlit as st
from pathlib import Path
from engine.paths import MEDIA_DIR


def render():
    st.header("🖼️ Media Gallery")

    media_dir = MEDIA_DIR

    tab1, tab2, tab3 = st.tabs(["🖼️ Images", "🎬 Videos", "🎵 Audio"])

    with tab1:
        _show_media(media_dir / "images", "image")
    with tab2:
        _show_media(media_dir / "video", "video")
    with tab3:
        _show_media(media_dir / "voice", "audio")


def _show_media(directory: Path, media_type: str):
    """Show media files from a directory."""
    if not directory.exists():
        st.info(f"No {media_type} directory found at {directory}")
        return

    extensions = {
        "image": {".png", ".jpg", ".jpeg", ".webp", ".gif"},
        "video": {".mp4", ".avi", ".webm", ".mov"},
        "audio": {".wav", ".mp3", ".ogg", ".flac"},
    }

    exts = extensions.get(media_type, set())
    files = sorted(
        [f for f in directory.rglob("*") if f.suffix.lower() in exts],
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )

    st.caption(f"{len(files)} {media_type} file(s)")

    if not files:
        st.info(f"No {media_type} files found. Generate some using the scenes!")
        return

    # Grid layout
    cols_per_row = 3 if media_type == "image" else 1
    for i in range(0, len(files[:50]), cols_per_row):
        cols = st.columns(cols_per_row)
        for j, col in enumerate(cols):
            idx = i + j
            if idx >= len(files[:50]):
                break
            f = files[idx]
            with col:
                if media_type == "image":
                    try:
                        st.image(str(f), caption=f.name, use_container_width=True)
                    except Exception:
                        st.markdown(f"📷 `{f.name}`")
                elif media_type == "video":
                    try:
                        st.video(str(f))
                    except Exception:
                        st.markdown(f"🎬 `{f.name}`")
                elif media_type == "audio":
                    try:
                        st.audio(str(f))
                    except Exception:
                        st.markdown(f"🎵 `{f.name}`")

                st.caption(f"{f.name} ({f.stat().st_size / 1024:.1f} KB)")
