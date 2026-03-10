"""Phase 3 — NeonPhone panel integration tests.

Validates the rebuilt phone slide-out panel:
  - CSS structure and cyberpunk styling
  - JS class structure and API integration
  - Lock screen, home screen, app grid
  - Correct API routes (thread-based, not contact-based)
  - Keyboard shortcuts
  - Socket.IO integration
  - All 9 apps defined
  - Fallback for offline phone scene
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent

# ── File paths ───────────────────────────────────────────────────────────────

PHONE_CSS = ROOT / "content" / "shared" / "static" / "css" / "cosysim-phone-panel.css"
PHONE_JS = ROOT / "content" / "shared" / "static" / "js" / "cosysim-phone-panel.js"
PHONE_TEMPLATE = ROOT / "content" / "scenes" / "phone" / "templates" / "phone_ui_v2.html"
PHONE_SCENE = ROOT / "content" / "scenes" / "phone" / "phone_scene_v2.py"


@pytest.fixture(scope="module")
def css_content() -> str:
    return PHONE_CSS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def js_content() -> str:
    return PHONE_JS.read_text(encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════════════
# 1. File Existence
# ═══════════════════════════════════════════════════════════════════════════════


class TestFileExistence:
    """Phone panel assets exist on disk."""

    def test_css_exists(self):
        assert PHONE_CSS.is_file()

    def test_js_exists(self):
        assert PHONE_JS.is_file()

    def test_phone_ui_template_exists(self):
        assert PHONE_TEMPLATE.is_file()

    def test_phone_scene_exists(self):
        assert PHONE_SCENE.is_file()


# ═══════════════════════════════════════════════════════════════════════════════
# 2. CSS Structure
# ═══════════════════════════════════════════════════════════════════════════════


class TestCSSStructure:
    """CSS contains all required component selectors and cyberpunk styling."""

    # Panel frame
    def test_panel_class(self, css_content):
        assert ".cs-phone-panel" in css_content

    def test_panel_open(self, css_content):
        assert ".cs-phone-panel.open" in css_content

    def test_overlay(self, css_content):
        assert ".cs-phone-overlay" in css_content

    def test_overlay_open(self, css_content):
        assert ".cs-phone-overlay.open" in css_content

    # Lock screen
    def test_lock_screen(self, css_content):
        assert ".cs-phone-lock" in css_content

    def test_lock_unlocked(self, css_content):
        assert ".cs-phone-lock.unlocked" in css_content

    def test_lock_time(self, css_content):
        assert ".cs-phone-lock-time" in css_content

    def test_lock_date(self, css_content):
        assert ".cs-phone-lock-date" in css_content

    def test_lock_hint(self, css_content):
        assert ".cs-phone-lock-hint" in css_content

    def test_lock_grid_animation(self, css_content):
        assert ".cs-phone-lock-grid" in css_content
        assert "cs-grid-drift" in css_content

    def test_lock_notifications(self, css_content):
        assert ".cs-phone-lock-notif" in css_content
        assert ".cs-lock-notif-item" in css_content

    # Status bar
    def test_statusbar(self, css_content):
        assert ".cs-phone-statusbar" in css_content

    def test_signal_dot(self, css_content):
        assert ".cs-phone-signal-dot" in css_content

    def test_signal_dot_offline(self, css_content):
        assert ".cs-phone-signal-dot.offline" in css_content

    # Home screen
    def test_home_screen(self, css_content):
        assert ".cs-phone-home" in css_content

    def test_greeting(self, css_content):
        assert ".cs-phone-greeting" in css_content

    # App grid
    def test_app_grid(self, css_content):
        assert ".cs-app-grid" in css_content
        assert "grid-template-columns" in css_content

    def test_app_icon(self, css_content):
        assert ".cs-app-icon" in css_content

    def test_app_icon_circle(self, css_content):
        assert ".cs-app-icon-circle" in css_content

    def test_app_badge(self, css_content):
        assert ".cs-app-badge" in css_content

    def test_app_icon_label(self, css_content):
        assert ".cs-app-icon-label" in css_content

    # Dock
    def test_dock(self, css_content):
        assert ".cs-phone-dock" in css_content

    def test_dock_btn(self, css_content):
        assert ".cs-dock-btn" in css_content

    # App view
    def test_appview(self, css_content):
        assert ".cs-phone-appview" in css_content

    def test_appview_active(self, css_content):
        assert ".cs-phone-appview.active" in css_content

    def test_app_header(self, css_content):
        assert ".cs-app-header" in css_content

    def test_app_back(self, css_content):
        assert ".cs-app-back" in css_content

    def test_app_body(self, css_content):
        assert ".cs-app-body" in css_content

    # Messages app
    def test_thread_list(self, css_content):
        assert ".cs-thread-list" in css_content

    def test_thread_item(self, css_content):
        assert ".cs-thread-item" in css_content

    def test_thread_avatar(self, css_content):
        assert ".cs-thread-avatar" in css_content

    def test_thread_badge(self, css_content):
        assert ".cs-thread-badge" in css_content

    def test_chat_messages(self, css_content):
        assert ".cs-chat-messages" in css_content

    def test_msg_them(self, css_content):
        assert ".cs-msg-them" in css_content

    def test_msg_me(self, css_content):
        assert ".cs-msg-me" in css_content

    def test_msg_typing(self, css_content):
        assert ".cs-msg-typing" in css_content

    def test_typing_dots(self, css_content):
        assert ".cs-msg-typing-dot" in css_content

    def test_chat_input(self, css_content):
        assert ".cs-chat-input" in css_content

    def test_chat_send(self, css_content):
        assert ".cs-chat-send" in css_content

    # Contacts app
    def test_contact_list(self, css_content):
        assert ".cs-contact-list" in css_content

    def test_contact_item(self, css_content):
        assert ".cs-contact-item" in css_content

    def test_contact_avatar(self, css_content):
        assert ".cs-contact-avatar" in css_content

    def test_contact_bio(self, css_content):
        assert ".cs-contact-bio" in css_content

    # News app
    def test_news_list(self, css_content):
        assert ".cs-news-list" in css_content

    def test_news_item(self, css_content):
        assert ".cs-news-item" in css_content

    def test_news_headline(self, css_content):
        assert ".cs-news-headline" in css_content

    def test_news_category(self, css_content):
        assert ".cs-news-category" in css_content

    # Wallet app
    def test_wallet_balance(self, css_content):
        assert ".cs-wallet-balance" in css_content

    def test_wallet_amount(self, css_content):
        assert ".cs-wallet-amount" in css_content

    def test_wallet_stats(self, css_content):
        assert ".cs-wallet-stats" in css_content

    def test_wallet_transactions(self, css_content):
        assert ".cs-wallet-tx" in css_content

    # Gallery app
    def test_gallery_grid(self, css_content):
        assert ".cs-gallery-grid" in css_content

    def test_gallery_thumb(self, css_content):
        assert ".cs-gallery-thumb" in css_content

    # Settings app
    def test_settings_list(self, css_content):
        assert ".cs-settings-list" in css_content

    def test_settings_toggle(self, css_content):
        assert ".cs-toggle" in css_content

    def test_settings_group(self, css_content):
        assert ".cs-settings-group" in css_content

    # Toast notification
    def test_toast(self, css_content):
        assert ".cs-phone-toast" in css_content

    def test_toast_show(self, css_content):
        assert ".cs-phone-toast.show" in css_content

    # Offline banner
    def test_offline_banner(self, css_content):
        assert ".cs-phone-offline-banner" in css_content

    # Cyberpunk colors (neon green)
    def test_cyberpunk_neon_green(self, css_content):
        assert "#00ffa0" in css_content

    def test_cyberpunk_background(self, css_content):
        assert "#06060e" in css_content

    # Animations
    def test_grid_drift_animation(self, css_content):
        assert "@keyframes cs-grid-drift" in css_content

    def test_hint_pulse_animation(self, css_content):
        assert "@keyframes cs-hint-pulse" in css_content

    def test_typing_animation(self, css_content):
        assert "@keyframes cs-typing" in css_content

    def test_spin_animation(self, css_content):
        assert "@keyframes cs-spin" in css_content

    def test_notif_in_animation(self, css_content):
        assert "@keyframes cs-notif-in" in css_content

    # Responsive
    def test_responsive_breakpoint(self, css_content):
        assert "@media (max-width: 480px)" in css_content

    def test_reduced_motion(self, css_content):
        assert "prefers-reduced-motion" in css_content


# ═══════════════════════════════════════════════════════════════════════════════
# 3. JS Structure & Class
# ═══════════════════════════════════════════════════════════════════════════════


class TestJSStructure:
    """JS has NeonPhone class with correct structure and API routes."""

    def test_iife_wrapper(self, js_content):
        assert "(function" in js_content
        assert "})();" in js_content
        assert "'use strict'" in js_content

    def test_neonphone_class(self, js_content):
        assert "class NeonPhone" in js_content

    def test_exports_phone_panel(self, js_content):
        assert "window.PhonePanel = instance" in js_content

    def test_phone_port(self, js_content):
        assert "PHONE_PORT = 5555" in js_content

    def test_phone_base(self, js_content):
        assert "PHONE_BASE" in js_content
        assert "localhost" in js_content


class TestJSApps:
    """All 9 apps are defined in the APPS array."""

    @pytest.fixture(scope="class")
    def apps_block(self, js_content: str) -> str:
        start = js_content.index("const APPS")
        end = js_content.index("];", start) + 2
        return js_content[start:end]

    @pytest.mark.parametrize("app_id", [
        "messages", "contacts", "news", "wallet", "gallery",
        "hacker", "ghost", "settings", "expand",
    ])
    def test_app_defined(self, apps_block, app_id):
        assert f"'{app_id}'" in apps_block

    def test_dock_apps(self, js_content):
        assert "DOCK_APPS" in js_content
        assert "'messages'" in js_content
        assert "'contacts'" in js_content
        assert "'news'" in js_content
        assert "'wallet'" in js_content


class TestJSAPIRoutes:
    """Phone panel uses correct thread-based API routes."""

    def test_threads_endpoint(self, js_content):
        assert "/api/threads" in js_content

    def test_thread_messages_endpoint(self, js_content):
        assert "/api/thread/" in js_content
        assert "/messages" in js_content

    def test_thread_send_endpoint(self, js_content):
        assert "/api/thread/" in js_content
        assert "/send" in js_content

    def test_contacts_endpoint(self, js_content):
        assert "/api/contacts" in js_content

    def test_news_endpoint(self, js_content):
        assert "/api/news/feed" in js_content

    def test_economy_endpoint(self, js_content):
        assert "/api/economy" in js_content

    def test_gallery_endpoint(self, js_content):
        assert "/api/gallery" in js_content

    def test_hacker_targets_endpoint(self, js_content):
        assert "/api/hacker/targets" in js_content

    def test_ghost_endpoint(self, js_content):
        assert "/api/world/send_ghost" in js_content

    def test_autotxt_mute_endpoint(self, js_content):
        assert "/api/admin/autotxt-mute" in js_content

    def test_wipe_messages_endpoint(self, js_content):
        assert "/api/admin/wipe-messages" in js_content

    def test_dm_create_endpoint(self, js_content):
        assert "/api/threads/dm" in js_content

    def test_no_legacy_messages_endpoint(self, js_content):
        """Must NOT use old /api/messages/<id> route."""
        assert "/api/messages/" not in js_content

    def test_no_legacy_send_endpoint(self, js_content):
        """Must NOT use old /api/send route (without thread id)."""
        # The only /api/send usage should be as part of /api/world/send_ghost
        count = js_content.count("'/api/send'") + js_content.count('"/api/send"')
        assert count == 0, "Found legacy /api/send endpoint"


class TestJSFeatures:
    """Key features are implemented."""

    # Lock screen
    def test_lock_screen_state(self, js_content):
        assert "_unlocked" in js_content

    def test_unlock_method(self, js_content):
        assert "_unlock()" in js_content or "_unlock" in js_content

    def test_lock_tap_hint(self, js_content):
        assert "TAP TO DECRYPT" in js_content

    # Keyboard shortcut
    def test_keyboard_binding(self, js_content):
        assert "_bindKeyboard" in js_content

    def test_p_key_toggle(self, js_content):
        assert "e.key === 'p'" in js_content or "e.key === 'P'" in js_content

    def test_escape_key(self, js_content):
        assert "Escape" in js_content

    # Socket.IO
    def test_socket_connect(self, js_content):
        assert "_connectSocket" in js_content
        assert "io(PHONE_BASE" in js_content or "io(" in js_content

    def test_socket_new_message(self, js_content):
        assert "new_message" in js_content

    def test_socket_world_alert(self, js_content):
        assert "world_alert" in js_content

    # Toast
    def test_show_toast(self, js_content):
        assert "_showToast" in js_content

    # Badge
    def test_update_badge(self, js_content):
        assert "_updateBadge" in js_content
        assert "updatePhoneBadge" in js_content

    # Offline handling
    def test_check_online(self, js_content):
        assert "_checkOnline" in js_content
        assert "_online" in js_content

    def test_offline_retry(self, js_content):
        assert "_retryInterval" in js_content

    # App navigation
    def test_open_app(self, js_content):
        assert "openApp(" in js_content

    def test_close_app(self, js_content):
        assert "closeApp()" in js_content

    # Clock
    def test_clock(self, js_content):
        assert "_startClock" in js_content
        assert "cs-phone-clock" in js_content

    # Typing indicator
    def test_typing_indicator(self, js_content):
        assert "cs-typing-indicator" in js_content
        assert "cs-msg-typing-dot" in js_content

    # XSS protection
    def test_escape_helper(self, js_content):
        assert "function _esc" in js_content

    # Public API
    def test_open_method(self, js_content):
        assert "open()" in js_content

    def test_close_method(self, js_content):
        assert "close()" in js_content

    def test_toggle_method(self, js_content):
        assert "toggle()" in js_content

    def test_add_notification(self, js_content):
        assert "addNotification(" in js_content

    def test_destroy_method(self, js_content):
        assert "destroy()" in js_content


class TestJSAppRenders:
    """Each app has a render method."""

    @pytest.mark.parametrize("app_method", [
        "_renderMessages",
        "_renderContacts",
        "_renderNews",
        "_renderWallet",
        "_renderGallery",
        "_renderHacker",
        "_renderGhost",
        "_renderSettings",
    ])
    def test_app_render_method(self, js_content, app_method):
        assert app_method in js_content


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Phone Scene API Route Validation
# ═══════════════════════════════════════════════════════════════════════════════


class TestPhoneSceneRoutes:
    """Verify phone scene has all routes the panel depends on."""

    @pytest.fixture(scope="class")
    def scene_content(self) -> str:
        return PHONE_SCENE.read_text(encoding="utf-8")

    @pytest.mark.parametrize("route", [
        "/api/threads",
        "/api/thread/<thread_id>/messages",
        "/api/thread/<thread_id>/send",
        "/api/contacts",
        "/api/news/feed",
        "/api/economy",
        "/api/gallery",
        "/api/hacker/targets",
        "/api/world/send_ghost",
        "/api/admin/autotxt-mute",
        "/api/admin/wipe-messages",
        "/api/threads/dm",
    ])
    def test_route_exists(self, scene_content, route):
        assert route in scene_content, f"Phone scene missing route: {route}"


# ═══════════════════════════════════════════════════════════════════════════════
# 5. No Legacy API Patterns
# ═══════════════════════════════════════════════════════════════════════════════


class TestNoLegacyPatterns:
    """Ensure old broken patterns are gone from the JS."""

    def test_no_polling_interval(self, js_content):
        """No 5-second polling — we use Socket.IO or on-demand fetch."""
        assert "setInterval" not in js_content or "5000" not in js_content.split("setInterval")[1].split(")")[0] if "setInterval" in js_content else True

    def test_no_old_class_name(self, js_content):
        """Old PhonePanel class replaced by NeonPhone."""
        assert "class PhonePanel" not in js_content

    def test_no_old_tabs(self, js_content):
        """Old tab-based UI replaced by app grid."""
        assert "switchTab" not in js_content

    def test_has_app_grid_rendering(self, js_content):
        assert "_renderAppGrid" in js_content

    def test_has_dock_rendering(self, js_content):
        assert "_renderDock" in js_content
