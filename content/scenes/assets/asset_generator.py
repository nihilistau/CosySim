"""
Asset Generator Scene
Standalone Streamlit app (port 8503) for generating images, videos, audio and stories.
Connects to:
  - ComfyUI  → http://192.168.8.150:8188
  - LM Studio → http://localhost:1234/v1
  - CosyVoice TTS (local)
"""

import streamlit as st
import sys
from pathlib import Path
from datetime import datetime

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

st.set_page_config(
    page_title="CosySim – Asset Generator",
    page_icon="🎨",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
.main-header {
    font-size: 2.8rem;
    font-weight: bold;
    background: linear-gradient(90deg, #0ea5e9 0%, #8b5cf6 60%, #ec4899 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    text-align: center;
    margin-bottom: 0.5rem;
}
.subtitle {
    color: #6b7280;
    text-align: center;
    margin-bottom: 2rem;
    font-size: 1.05rem;
}
.status-ok   { color: #22c55e; font-weight: bold; }
.status-err  { color: #ef4444; font-weight: bold; }
</style>
""", unsafe_allow_html=True)


# ── Helpers ───────────────────────────────────────────────────────────────────
@st.cache_resource
def get_comfyui():
    from content.simulation.services.comfyui_client import get_comfyui_client
    return get_comfyui_client()


@st.cache_resource
def get_llm():
    from content.simulation.services.llm_service import get_llm_service
    return get_llm_service()


def get_character_list():
    try:
        from engine.assets import AssetManager
        am = AssetManager()
        return am.search(asset_type="character")
    except Exception:
        return []


def get_character(char_id: str):
    try:
        from content.simulation.database.db import Database
        from content.simulation.character_system.character import Character
        db = Database()
        return Character.load(char_id, db=db)
    except Exception:
        return None


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    st.markdown('<h1 class="main-header">🎨 Asset Generator</h1>', unsafe_allow_html=True)
    st.markdown('<p class="subtitle">Generate images, videos, voices and stories for your characters</p>',
                unsafe_allow_html=True)

    # ── Sidebar status ──
    with st.sidebar:
        st.markdown("## 🔌 Service Status")

        comfy = get_comfyui()
        comfy_ok = comfy.is_available()
        st.markdown(
            f'ComfyUI: <span class="{"status-ok" if comfy_ok else "status-err"}">{"● Online" if comfy_ok else "● Offline"}</span>',
            unsafe_allow_html=True,
        )

        llm = get_llm()
        llm_ok = llm.is_available()
        st.markdown(
            f'LM Studio: <span class="{"status-ok" if llm_ok else "status-err"}">{"● Online" if llm_ok else "● Offline"}</span>',
            unsafe_allow_html=True,
        )

        st.markdown("---")
        st.markdown("## 🔗 Navigation")
        if st.button("🏠 Hub",           use_container_width=True):
            st.markdown("[Go to Hub](http://localhost:8500)")
        if st.button("🎛️ Admin Panel",   use_container_width=True):
            st.markdown("[Go to Admin](http://localhost:8502)")
        if st.button("📱 Phone Scene",   use_container_width=True):
            st.markdown("[Go to Phone](http://localhost:5555)")

        st.markdown("---")
        st.markdown(f"**Time:** {datetime.now().strftime('%H:%M:%S')}")
        if st.button("🔄 Refresh Status", use_container_width=True):
            st.cache_resource.clear()
            st.rerun()

    # ── Tabs ──
    tabs = st.tabs(["🖼️ Image", "🎬 Video Message", "🎤 Voice", "📖 Story / Script", "🗂️ Library"])

    with tabs[0]:
        _tab_image(comfy, comfy_ok)

    with tabs[1]:
        _tab_video()

    with tabs[2]:
        _tab_voice()

    with tabs[3]:
        _tab_story(llm, llm_ok)

    with tabs[4]:
        _tab_library()


# ── Tab: Image ────────────────────────────────────────────────────────────────
def _tab_image(comfy, comfy_ok):
    st.subheader("🖼️ Image Generation (ComfyUI)")

    if not comfy_ok:
        st.warning("⚠️ ComfyUI is offline (192.168.8.150:8188). Images will use offline placeholder.")

    col_left, col_right = st.columns([2, 1])

    with col_left:
        # Quick character fill
        char_list = get_character_list()
        char_options = {c['id']: c.get('name', c['id']) for c in char_list}
        selected_char_id = st.selectbox("Pre-fill from character", ["(manual)"] + list(char_options.keys()),
                                        format_func=lambda x: char_options.get(x, x))
        appearance_hint = ""
        if selected_char_id and selected_char_id != "(manual)":
            char = get_character(selected_char_id)
            if char:
                appearance_hint = getattr(char, "appearance", None) or char.description or ""

        pos_prompt = st.text_area("Positive Prompt",
                                  value=appearance_hint,
                                  placeholder="beautiful woman, brown hair, green eyes, smiling, outdoor, realistic, 8k",
                                  height=120)
        neg_prompt = st.text_area("Negative Prompt",
                                  value="blurry, low quality, extra limbs, bad anatomy, watermark",
                                  height=80)

    with col_right:
        width  = st.number_input("Width",  value=512, step=64, min_value=256, max_value=2048)
        height = st.number_input("Height", value=512, step=64, min_value=256, max_value=2048)
        mood   = st.selectbox("Mood / Vibe", ["none", "happy", "flirty", "seductive", "romantic", "sad", "excited", "neutral"])
        setting = st.selectbox("Setting", ["none", "casual", "bedroom", "beach", "gym", "night", "outdoor", "lingerie"])
        nsfw   = st.checkbox("Allow NSFW")
        num_images = st.number_input("Count", value=1, min_value=1, max_value=4)

    if st.button("🎨 Generate Image(s)", type="primary", use_container_width=True):
        save_dir = Path(project_root) / "content" / "simulation" / "media" / "images"
        save_dir.mkdir(parents=True, exist_ok=True)

        for i in range(int(num_images)):
            with st.spinner(f"Generating image {i+1}/{int(num_images)}..."):
                try:
                    # Enrich prompt with mood/setting
                    extra = ""
                    if mood != "none":
                        extra += f", {mood} expression"
                    if setting != "none":
                        extra += f", {setting} setting"

                    path = comfy.generate_image(
                        positive_prompt=pos_prompt + extra,
                        negative_prompt=neg_prompt,
                        save_dir=str(save_dir),
                    )
                    if path:
                        st.image(path, caption=f"Image {i+1}", use_column_width=True)
                        st.success(f"✅ Saved to {path}")
                    else:
                        st.error(f"Generation failed for image {i+1}")
                except Exception as e:
                    st.error(f"Error: {e}")


# ── Tab: Video ────────────────────────────────────────────────────────────────
def _tab_video():
    st.subheader("🎬 Video Message Generation")
    st.info("Generates a video of the character speaking text (image + TTS → FFmpeg).")

    char_list = get_character_list()
    char_options = {c['id']: c.get('name', c['id']) for c in char_list}

    if not char_options:
        st.warning("No characters found. Create a character in the Admin Panel first.")
        return

    sel_id = st.selectbox("Character", list(char_options.keys()), format_func=lambda x: char_options.get(x, x))
    text = st.text_area("Script (what the character says)", placeholder="Hey, I was thinking about you today...")
    mood = st.selectbox("Mood", ["happy", "flirty", "seductive", "romantic", "sad", "excited", "neutral"])
    duration = st.slider("Target duration (seconds)", 3.0, 30.0, 8.0, 0.5)

    if st.button("🎬 Generate Video Message", type="primary"):
        char = get_character(sel_id)
        if not char:
            st.error("Character not found.")
            return
        with st.spinner("Generating video message (may take a minute)..."):
            try:
                from content.simulation.database.db import Database
                from content.simulation.services.media_generator import MediaGenerator
                from content.simulation.services.voice_message import VoiceMessageGenerator
                from content.simulation.services.video_message import VideoMessageGenerator
                db  = Database()
                mg  = MediaGenerator()
                vmg = VoiceMessageGenerator(db=db)
                vdg = VideoMessageGenerator(media_gen=mg, voice_gen=vmg, db=db)
                result = vdg.generate_video_message(
                    character_id=char.id,
                    character_name=char.name,
                    character_description=getattr(char, "appearance", None) or char.description or "",
                    text=text,
                    mood=mood,
                    duration=duration,
                )
                if result:
                    st.success(f"✅ Generated: {result['filename']}")
                    st.video(result["filepath"])
                else:
                    st.warning("Generation returned nothing. Ensure ComfyUI and CosyVoice are running.")
            except Exception as e:
                st.error(f"Error: {e}")


# ── Tab: Voice ────────────────────────────────────────────────────────────────
def _tab_voice():
    st.subheader("🎤 Voice Message Generation (CosyVoice TTS)")

    char_list = get_character_list()
    char_options = {c['id']: c.get('name', c['id']) for c in char_list}

    if not char_options:
        st.warning("No characters found. Create one in Admin Panel first.")
        return

    sel_id  = st.selectbox("Character", list(char_options.keys()), format_func=lambda x: char_options.get(x, x), key="voice_char")
    text    = st.text_area("Text to speak", placeholder="Hey, just thinking of you ❤️", key="voice_text")
    emotion = st.selectbox("Emotion", ["happy", "flirty", "sad", "excited", "neutral", "romantic"], key="voice_emo")

    if st.button("🎤 Generate Voice Message", type="primary"):
        char = get_character(sel_id)
        if not char:
            st.error("Character not found.")
            return
        with st.spinner("Generating TTS audio..."):
            try:
                from content.simulation.database.db import Database
                from content.simulation.services.voice_message import VoiceMessageGenerator
                db  = Database()
                vmg = VoiceMessageGenerator(db=db)
                result = vmg.generate_voice_message(
                    character_id=char.id,
                    character_name=char.name,
                    text=text,
                    emotion=emotion,
                )
                if result:
                    st.success(f"✅ {result['filename']} ({result.get('duration', '?'):.1f}s)")
                    st.audio(result["filepath"])
                else:
                    st.warning("TTS not available or returned nothing.")
            except Exception as e:
                st.error(f"Error: {e}")


# ── Tab: Story ────────────────────────────────────────────────────────────────
def _tab_story(llm, llm_ok):
    st.subheader("📖 Story / Script Generator (LLM)")

    if not llm_ok:
        st.warning("⚠️ LM Studio offline. Story generation unavailable.")

    scenario_type = st.selectbox("Scenario Type", [
        "Romantic date scene",
        "Morning chat",
        "Flirty text exchange",
        "Intimate scenario",
        "Adventure / action scene",
        "Custom (describe below)",
    ])

    char_list = get_character_list()
    char_options = {c['id']: c.get('name', c['id']) for c in char_list}
    sel_id = st.selectbox("Character (optional)", ["(none)"] + list(char_options.keys()),
                          format_func=lambda x: char_options.get(x, x), key="story_char")

    custom_prompt = st.text_area(
        "Custom prompt / extra context",
        placeholder="Emma and the user are meeting for coffee for the first time after weeks of texting...",
        height=120,
    )

    col1, col2, col3 = st.columns(3)
    length = col1.slider("Length (tokens)", 100, 4000, 800, 50)
    temp   = col2.slider("Temperature", 0.1, 2.0, 0.9, 0.05)
    nsfw   = col3.checkbox("Explicit content OK")

    if st.button("📖 Generate Story", type="primary", disabled=not llm_ok):
        char_context = ""
        if sel_id and sel_id != "(none)":
            char = get_character(sel_id)
            if char:
                char_context = f"\nCharacter: {char.name}, {char.age} years old, {getattr(char, 'appearance', char.description or '')}.\n"

        system_msg = (
            "You are a creative fiction writer producing immersive, engaging scenarios. "
            "Write in second-person (you/your) for an interactive feel. "
            + ("Explicit adult content is allowed and welcome. " if nsfw else "Keep content tasteful and romantic. ")
        )

        user_msg = f"Scenario type: {scenario_type}\n{char_context}{custom_prompt}"

        with st.spinner("Writing story..."):
            try:
                result = llm.chat(
                    messages=[{"role": "user", "content": user_msg}],
                    system_prompt=system_msg,
                    temperature=temp,
                    max_tokens=length,
                )
                st.markdown("---")
                st.markdown(result)

                # Save option
                if st.button("💾 Save story to file"):
                    out_dir = Path(project_root) / "content" / "simulation" / "media" / "stories"
                    out_dir.mkdir(parents=True, exist_ok=True)
                    fname = out_dir / f"story_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                    fname.write_text(result, encoding="utf-8")
                    st.success(f"Saved to {fname}")
            except Exception as e:
                st.error(f"Error: {e}")


# ── Tab: Library ──────────────────────────────────────────────────────────────
def _tab_library():
    st.subheader("🗂️ Generated Asset Library")

    media_root = Path(project_root) / "content" / "simulation" / "media"
    categories = {
        "🖼️ Images": media_root / "images",
        "🎬 Videos": media_root / "video",
        "🎤 Voice":  media_root / "voice",
        "📖 Stories": media_root / "stories",
    }

    for label, path in categories.items():
        with st.expander(label, expanded=False):
            if not path.exists() or not list(path.iterdir()):
                st.info("No files yet.")
                continue

            files = sorted(path.iterdir(), key=lambda f: f.stat().st_mtime, reverse=True)
            for f in files[:20]:
                c1, c2 = st.columns([4, 1])
                size_kb = f.stat().st_size // 1024
                c1.markdown(f"`{f.name}` — {size_kb} KB — {datetime.fromtimestamp(f.stat().st_mtime).strftime('%Y-%m-%d %H:%M')}")
                ext = f.suffix.lower()
                if ext in (".png", ".jpg", ".jpeg", ".webp"):
                    if c2.button("👁️", key=f"view_{f.name}"):
                        st.image(str(f), caption=f.name, use_column_width=True)
                elif ext in (".mp4", ".webm"):
                    if c2.button("▶️", key=f"play_{f.name}"):
                        st.video(str(f))
                elif ext in (".wav", ".mp3", ".ogg"):
                    if c2.button("🔊", key=f"audio_{f.name}"):
                        st.audio(str(f))


if __name__ == "__main__":
    main()
