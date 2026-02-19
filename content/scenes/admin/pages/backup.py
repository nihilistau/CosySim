"""Backup & Restore page."""
import streamlit as st
import shutil
from pathlib import Path
from datetime import datetime


def render():
    st.header("💾 Backup & Restore")

    tab1, tab2 = st.tabs(["📤 Backup", "📥 Restore"])
    backup_dir = Path(__file__).parent.parent.parent.parent.parent / "backups"

    with tab1:
        backup_name = st.text_input(
            "Name",
            f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            key="bk_name",
        )
        include_media = st.checkbox("Include media files", key="bk_media")

        if st.button("📤 Create Backup", type="primary"):
            try:
                backup_dir.mkdir(exist_ok=True)
                backup_path = backup_dir / backup_name
                backup_path.mkdir(exist_ok=True)

                # Backup asset DB
                db_path = st.session_state.asset_manager.db_path
                if Path(db_path).exists():
                    shutil.copy2(db_path, backup_path / "assets.db")

                # Backup simulation DB
                sim_db = Path(__file__).parent.parent.parent.parent / "simulation" / "database" / "cosysim.db"
                if sim_db.exists():
                    shutil.copy2(sim_db, backup_path / "cosysim.db")

                # Backup config
                config_dir = Path(__file__).parent.parent.parent.parent.parent / "config"
                if config_dir.exists():
                    shutil.copytree(config_dir, backup_path / "config", dirs_exist_ok=True)

                st.success(f"✅ Backup created: {backup_name}")
            except Exception as e:
                st.error(f"Failed: {e}")

    with tab2:
        if not backup_dir.exists():
            st.info("No backup directory")
            return

        backups = sorted([d.name for d in backup_dir.iterdir() if d.is_dir()], reverse=True)
        if not backups:
            st.info("No backups found")
            return

        selected = st.selectbox("Select Backup", backups, key="bk_sel")
        st.warning("⚠️ This will overwrite current data!")

        if st.checkbox("I understand and want to proceed", key="bk_confirm"):
            if st.button("📥 Restore", key="bk_restore"):
                try:
                    bp = backup_dir / selected

                    # Restore asset DB
                    asset_backup = bp / "assets.db"
                    if asset_backup.exists():
                        shutil.copy2(asset_backup, st.session_state.asset_manager.db_path)

                    # Restore simulation DB
                    sim_backup = bp / "cosysim.db"
                    if sim_backup.exists():
                        sim_db = Path(__file__).parent.parent.parent.parent / "simulation" / "database" / "cosysim.db"
                        shutil.copy2(sim_backup, sim_db)

                    st.success("✅ Restored!")
                except Exception as e:
                    st.error(f"Failed: {e}")
