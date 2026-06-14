"""
Assistant Platform — Authentication
=====================================

Simple session-based auth with SQLite user storage.
Optional — can be disabled via config.

Version: v1.0.0 [2026-03-23]
Author:  CosySim Team

Change Log:
    v1.0.0 [2026-03-23] — Initial auth: register, login, logout, session
"""
from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Dict, Optional

from flask import Blueprint, jsonify, redirect, request, session, url_for

from apps.assistant.config import DATABASE_PATH

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)

AUTH_ENABLED = True  # Set False to disable auth entirely


# ──── Database ───────────────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DATABASE_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_auth_table() -> None:
    """Create users table if it doesn't exist."""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_login TEXT DEFAULT NULL,
            is_admin INTEGER DEFAULT 0
        );
    """)
    conn.commit()
    conn.close()


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), 100000
    ).hex()


def create_user(username: str, password: str, is_admin: bool = False) -> Optional[Dict]:
    """Create a new user. Returns user dict or None if username taken."""
    user_id = str(uuid.uuid4())
    salt = os.urandom(32).hex()
    pw_hash = _hash_password(password, salt)
    now = datetime.now(timezone.utc).isoformat()

    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO users (id, username, password_hash, salt, created_at, is_admin) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, username, pw_hash, salt, now, int(is_admin)),
        )
        conn.commit()
        return {"id": user_id, "username": username, "is_admin": is_admin}
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()


def verify_user(username: str, password: str) -> Optional[Dict]:
    """Verify credentials. Returns user dict or None."""
    conn = _get_conn()
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()

    if not row:
        return None

    pw_hash = _hash_password(password, row["salt"])
    if pw_hash != row["password_hash"]:
        return None

    # Update last_login
    conn = _get_conn()
    conn.execute(
        "UPDATE users SET last_login = ? WHERE id = ?",
        (datetime.now(timezone.utc).isoformat(), row["id"]),
    )
    conn.commit()
    conn.close()

    return {"id": row["id"], "username": row["username"], "is_admin": bool(row["is_admin"])}


def get_user_count() -> int:
    """Get total number of registered users."""
    conn = _get_conn()
    count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    conn.close()
    return count


# ──── Auth Decorator ─────────────────────────────────────────────────

def login_required(f):
    """Decorator to require authentication. Skips if AUTH_ENABLED is False."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not AUTH_ENABLED:
            return f(*args, **kwargs)
        if "user_id" not in session:
            if request.is_json or request.path.startswith("/api/") or request.path.startswith("/v1/"):
                return jsonify({"error": "authentication required"}), 401
            return redirect(url_for("auth.login_page"))
        return f(*args, **kwargs)
    return decorated


def get_current_user_id() -> Optional[str]:
    """Get the current session user ID, or None if not logged in."""
    if not AUTH_ENABLED:
        return "default"
    return session.get("user_id")


# ──── Routes ─────────────────────────────────────────────────────────

@auth_bp.route("/login", methods=["GET"])
def login_page():
    """Serve login page. If no users exist, redirect to register."""
    if not AUTH_ENABLED:
        return redirect("/")
    if get_user_count() == 0:
        return redirect(url_for("auth.register_page"))
    return """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Login — CosySim Assistant</title>
<link rel="stylesheet" href="/shared/css/design_tokens.css">
<link rel="stylesheet" href="/static/css/assistant.css">
<style>
.auth-form { max-width:360px; margin:15vh auto; padding:32px; background:var(--cs-bg-panel); border:1px solid var(--cs-glass-border); border-radius:12px; }
.auth-form h2 { color:var(--accent); margin-bottom:20px; text-align:center; }
.auth-form input { width:100%; padding:10px 12px; margin-bottom:12px; background:var(--cs-bg-dark); color:var(--cs-text-primary); border:1px solid var(--cs-glass-border); border-radius:6px; font-family:inherit; font-size:14px; }
.auth-form input:focus { outline:none; border-color:var(--accent); }
.auth-form button { width:100%; padding:10px; margin-top:8px; }
.auth-form .auth-link { text-align:center; margin-top:16px; font-size:13px; color:var(--cs-text-secondary); }
.auth-form .auth-link a { color:var(--accent); text-decoration:none; }
.auth-error { color:var(--cs-red); font-size:13px; text-align:center; margin-bottom:12px; }
</style></head>
<body style="background:var(--cs-bg-deepest)">
<form class="auth-form" method="POST" action="/auth/login">
  <h2>◈ Login</h2>
  <div id="error" class="auth-error"></div>
  <input name="username" placeholder="Username" required autofocus>
  <input name="password" type="password" placeholder="Password" required>
  <button class="cs-btn cs-btn--accent" type="submit">Login</button>
  <div class="auth-link"><a href="/auth/register">Create account</a></div>
</form>
</body></html>"""


@auth_bp.route("/login", methods=["POST"])
def login_submit():
    if request.is_json:
        data = request.get_json()
    else:
        data = request.form

    username = data.get("username", "")
    password = data.get("password", "")

    user = verify_user(username, password)
    if not user:
        if request.is_json:
            return jsonify({"error": "invalid credentials"}), 401
        return redirect(url_for("auth.login_page") + "?error=1")

    session["user_id"] = user["id"]
    session["username"] = user["username"]
    session["is_admin"] = user["is_admin"]

    if request.is_json:
        return jsonify({"ok": True, "user": user})
    return redirect("/")


@auth_bp.route("/register", methods=["GET"])
def register_page():
    if not AUTH_ENABLED:
        return redirect("/")
    return """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Register — CosySim Assistant</title>
<link rel="stylesheet" href="/shared/css/design_tokens.css">
<link rel="stylesheet" href="/static/css/assistant.css">
<style>
.auth-form { max-width:360px; margin:15vh auto; padding:32px; background:var(--cs-bg-panel); border:1px solid var(--cs-glass-border); border-radius:12px; }
.auth-form h2 { color:var(--accent); margin-bottom:20px; text-align:center; }
.auth-form input { width:100%; padding:10px 12px; margin-bottom:12px; background:var(--cs-bg-dark); color:var(--cs-text-primary); border:1px solid var(--cs-glass-border); border-radius:6px; font-family:inherit; font-size:14px; }
.auth-form input:focus { outline:none; border-color:var(--accent); }
.auth-form button { width:100%; padding:10px; margin-top:8px; }
.auth-form .auth-link { text-align:center; margin-top:16px; font-size:13px; color:var(--cs-text-secondary); }
.auth-form .auth-link a { color:var(--accent); text-decoration:none; }
</style></head>
<body style="background:var(--cs-bg-deepest)">
<form class="auth-form" method="POST" action="/auth/register">
  <h2>◈ Create Account</h2>
  <input name="username" placeholder="Username" required autofocus>
  <input name="password" type="password" placeholder="Password" required>
  <input name="confirm" type="password" placeholder="Confirm password" required>
  <button class="cs-btn cs-btn--accent" type="submit">Register</button>
  <div class="auth-link"><a href="/auth/login">Already have an account?</a></div>
</form>
</body></html>"""


@auth_bp.route("/register", methods=["POST"])
def register_submit():
    if request.is_json:
        data = request.get_json()
    else:
        data = request.form

    username = data.get("username", "").strip()
    password = data.get("password", "")
    confirm = data.get("confirm", "")

    if len(username) < 2:
        return jsonify({"error": "username too short"}), 400
    if len(password) < 4:
        return jsonify({"error": "password too short"}), 400
    if password != confirm:
        return jsonify({"error": "passwords don't match"}), 400

    # First user is admin
    is_admin = get_user_count() == 0
    user = create_user(username, password, is_admin=is_admin)

    if not user:
        return jsonify({"error": "username taken"}), 400

    session["user_id"] = user["id"]
    session["username"] = user["username"]
    session["is_admin"] = user["is_admin"]

    if request.is_json:
        return jsonify({"ok": True, "user": user})
    return redirect("/")


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login_page"))


@auth_bp.route("/me")
def current_user():
    if "user_id" not in session:
        return jsonify({"authenticated": False})
    return jsonify({
        "authenticated": True,
        "user_id": session["user_id"],
        "username": session.get("username"),
        "is_admin": session.get("is_admin", False),
    })
