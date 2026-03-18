"""
Secret Manager for CosySim.

Provides a centralized vault for API keys, tokens, and other secrets with:
- Fernet encryption at rest (data/secrets.db)
- SQLite audit logging of all access and rotation events
- TTL-based expiry and alerting via Nexus
- Auto-import from environment variables and config file
"""

import json
import logging
import os
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fernet availability check
# ---------------------------------------------------------------------------
try:
    from cryptography.fernet import Fernet as _Fernet

    _FERNET_AVAILABLE = True
except ImportError:
    _FERNET_AVAILABLE = False
    logger.warning(
        "cryptography package not installed; secrets will be stored as plaintext. "
        "Install it with: pip install cryptography"
    )


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SecretType(str, Enum):
    """Classification of secret values."""

    API_KEY = "api_key"
    BEARER_TOKEN = "bearer_token"
    DB_PATH = "db_path"
    PASSWORD = "password"
    CERT = "cert"
    WEBHOOK = "webhook"
    OTHER = "other"


class SecretSource(str, Enum):
    """Origin of a secret value."""

    ENV_VAR = "env_var"
    CONFIG_FILE = "config_file"
    VAULT_FILE = "vault_file"
    RUNTIME = "runtime"


# ---------------------------------------------------------------------------
# SecretEntry dataclass
# ---------------------------------------------------------------------------


@dataclass
class SecretEntry:
    """A single secret stored in the vault.

    Attributes:
        name: Unique identifier for the secret.
        value: Plaintext secret value (never logged or serialised).
        secret_type: Category of the secret.
        created_at: UTC timestamp of initial creation.
        expires_at: Optional UTC expiry timestamp.
        rotated_at: UTC timestamp of most recent rotation.
        source: Where the secret value originated.
        tags: Arbitrary string labels for filtering.
    """

    name: str
    value: str
    secret_type: SecretType = SecretType.OTHER
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = None
    rotated_at: Optional[datetime] = None
    source: SecretSource = SecretSource.RUNTIME
    tags: List[str] = field(default_factory=list)

    def is_expired(self) -> bool:
        """Return True if this secret has passed its expiry timestamp."""
        if self.expires_at is None:
            return False
        return datetime.now(timezone.utc) > self.expires_at

    def expires_soon(self, threshold_seconds: int = 3600) -> bool:
        """Return True if the secret expires within *threshold_seconds*.

        Args:
            threshold_seconds: Window in seconds to consider "soon".

        Returns:
            True when the secret will expire within the threshold window.
        """
        if self.expires_at is None:
            return False
        remaining = (self.expires_at - datetime.now(timezone.utc)).total_seconds()
        return 0 < remaining < threshold_seconds


# ---------------------------------------------------------------------------
# Helper functions (module-level)
# ---------------------------------------------------------------------------


def _is_secret_key(key: str) -> bool:
    """Return True if a config key name suggests it holds a secret value.

    Args:
        key: The config key name (last segment of dot-notation path).

    Returns:
        True when the key looks like it contains secret material.
    """
    lower = key.lower()
    return any(
        kw in lower
        for kw in ("token", "key", "password", "secret", "credential", "bearer")
    )


def _infer_secret_type(name: str) -> SecretType:
    """Infer the most appropriate SecretType from a key name.

    Args:
        name: The key or variable name to classify.

    Returns:
        The best matching SecretType value.
    """
    lower = name.lower()
    if "bearer" in lower:
        return SecretType.BEARER_TOKEN
    if "token" in lower:
        return SecretType.BEARER_TOKEN
    if "api_key" in lower or "apikey" in lower:
        return SecretType.API_KEY
    if "password" in lower or "passwd" in lower:
        return SecretType.PASSWORD
    if "cert" in lower or "certificate" in lower:
        return SecretType.CERT
    if "webhook" in lower:
        return SecretType.WEBHOOK
    if "db" in lower or "database" in lower or "path" in lower:
        return SecretType.DB_PATH
    if "key" in lower:
        return SecretType.API_KEY
    return SecretType.OTHER


def _count_by(secrets: List[Dict], field_name: str) -> Dict[str, int]:
    """Count secrets grouped by a metadata field.

    Args:
        secrets: List of secret metadata dicts.
        field_name: Key to group by (e.g. ``"secret_type"``).

    Returns:
        Mapping of field value → count.
    """
    counts: Dict[str, int] = {}
    for s in secrets:
        val = s.get(field_name, "unknown")
        counts[val] = counts.get(val, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# SecretManager
# ---------------------------------------------------------------------------


class SecretManager:
    """Centralized vault for CosySim secrets.

    Secrets are encrypted with Fernet (AES-128-CBC + HMAC-SHA256) at rest in
    ``data/secrets.db``.  A rolling audit log records every access, creation,
    rotation, and deletion event.

    Args:
        db_path: Path to the SQLite database file.  Defaults to
            ``data/secrets.db``.
        key_file: Path for the Fernet key file.  Defaults to
            ``data/.secret_key``.

    Example:
        >>> sm = SecretManager()
        >>> sm.set("my_api_key", "tok_abc123", SecretType.API_KEY)
        >>> sm.get("my_api_key")
        'tok_abc123'
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        key_file: Optional[str] = None,
    ) -> None:
        self._lock = threading.Lock()

        data_dir = Path("data")
        data_dir.mkdir(exist_ok=True)

        self._db_path = db_path or str(data_dir / "secrets.db")
        self._key_file = key_file or str(data_dir / ".secret_key")

        # In-memory cache: name → SecretEntry
        self._cache: Dict[str, SecretEntry] = {}

        # Fernet cipher (None when cryptography is unavailable)
        self._fernet: Any = None
        if _FERNET_AVAILABLE:
            self._fernet = self._load_or_create_fernet_key()

        self._init_db()
        self._load_all()

    # ------------------------------------------------------------------
    # Encryption helpers
    # ------------------------------------------------------------------

    def _load_or_create_fernet_key(self) -> Any:
        """Load an existing Fernet key or generate a new one.

        Returns:
            A Fernet instance ready for encryption/decryption.
        """
        key_path = Path(self._key_file)
        if key_path.exists():
            raw = key_path.read_bytes().strip()
        else:
            raw = _Fernet.generate_key()
            key_path.parent.mkdir(parents=True, exist_ok=True)
            key_path.write_bytes(raw)
            try:
                key_path.chmod(0o600)
            except Exception:
                pass  # Windows doesn't support chmod
            logger.info("Generated new Fernet encryption key at %s", self._key_file)
        return _Fernet(raw)

    def _encrypt(self, value: str) -> str:
        """Encrypt *value* if Fernet is available, else return plaintext.

        Args:
            value: Plaintext secret value.

        Returns:
            Ciphertext token (or plaintext if encryption unavailable).
        """
        if self._fernet is not None:
            return self._fernet.encrypt(value.encode()).decode()
        return value

    def _decrypt(self, token: str) -> str:
        """Decrypt *token* if Fernet is available, else return as-is.

        Args:
            token: Ciphertext token (or plaintext).

        Returns:
            Decrypted secret value.
        """
        if self._fernet is not None:
            return self._fernet.decrypt(token.encode()).decode()
        return token

    # ------------------------------------------------------------------
    # Database initialisation and persistence
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        """Create SQLite tables if they do not already exist."""
        with sqlite3.connect(self._db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS secrets (
                    name           TEXT PRIMARY KEY,
                    encrypted_value TEXT NOT NULL,
                    secret_type    TEXT NOT NULL,
                    created_at     TEXT NOT NULL,
                    expires_at     TEXT,
                    rotated_at     TEXT,
                    source         TEXT NOT NULL,
                    tags           TEXT NOT NULL DEFAULT '[]'
                );
                CREATE TABLE IF NOT EXISTS secret_audit_log (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp   TEXT    NOT NULL,
                    event_type  TEXT    NOT NULL,
                    secret_name TEXT    NOT NULL,
                    actor       TEXT    NOT NULL DEFAULT 'system',
                    details     TEXT
                );
                """
            )

    def _load_all(self) -> None:
        """Load all secrets from the database into the in-memory cache."""
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                "SELECT name, encrypted_value, secret_type, created_at, "
                "expires_at, rotated_at, source, tags FROM secrets"
            ).fetchall()

        for row in rows:
            (
                name,
                encrypted_value,
                secret_type,
                created_at,
                expires_at,
                rotated_at,
                source,
                tags,
            ) = row
            try:
                value = self._decrypt(encrypted_value)
                entry = SecretEntry(
                    name=name,
                    value=value,
                    secret_type=SecretType(secret_type),
                    created_at=datetime.fromisoformat(created_at),
                    expires_at=datetime.fromisoformat(expires_at) if expires_at else None,
                    rotated_at=datetime.fromisoformat(rotated_at) if rotated_at else None,
                    source=SecretSource(source),
                    tags=json.loads(tags),
                )
                self._cache[name] = entry
            except Exception as exc:
                logger.error("Failed to load secret '%s' from DB: %s", name, exc)

    def _persist(self, entry: SecretEntry) -> None:
        """Write a single SecretEntry to the database (transactional).

        Args:
            entry: The entry to persist.
        """
        encrypted_value = self._encrypt(entry.value)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO secrets
                    (name, encrypted_value, secret_type, created_at,
                     expires_at, rotated_at, source, tags)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.name,
                    encrypted_value,
                    entry.secret_type.value,
                    entry.created_at.isoformat(),
                    entry.expires_at.isoformat() if entry.expires_at else None,
                    entry.rotated_at.isoformat() if entry.rotated_at else None,
                    entry.source.value,
                    json.dumps(entry.tags),
                ),
            )

    def _audit(
        self,
        event_type: str,
        secret_name: str,
        actor: str = "system",
        details: Optional[str] = None,
    ) -> None:
        """Append a row to the audit log (transactional).

        Args:
            event_type: One of: create, update, access, access_expired,
                rotate, delete.
            secret_name: Name of the affected secret.
            actor: Identity performing the action.
            details: Optional free-text context.
        """
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO secret_audit_log
                    (timestamp, event_type, secret_name, actor, details)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    event_type,
                    secret_name,
                    actor,
                    details,
                ),
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, name: str, default: Optional[str] = None) -> Optional[str]:
        """Retrieve a secret by name, honouring expiry.

        Args:
            name: Secret identifier.
            default: Value returned when the secret is absent or expired.

        Returns:
            Plaintext secret value, or *default*.
        """
        with self._lock:
            entry = self._cache.get(name)
            if entry is None:
                return default
            if entry.is_expired():
                logger.warning("Secret '%s' has expired and will not be returned.", name)
                self._audit("access_expired", name)
                return default
            self._audit("access", name)
            return entry.value

    def set(
        self,
        name: str,
        value: str,
        secret_type: SecretType = SecretType.OTHER,
        ttl_seconds: Optional[int] = None,
        tags: Optional[List[str]] = None,
        source: SecretSource = SecretSource.RUNTIME,
    ) -> None:
        """Store or update a secret.

        Args:
            name: Unique identifier for this secret.
            value: Plaintext secret value.
            secret_type: Category classification.
            ttl_seconds: Optional time-to-live.  Secret will expire after
                this many seconds from now.
            tags: Arbitrary string labels.
            source: Where this value originated.
        """
        with self._lock:
            existing = self._cache.get(name)
            expires_at: Optional[datetime] = None
            if ttl_seconds is not None:
                expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)

            entry = SecretEntry(
                name=name,
                value=value,
                secret_type=secret_type,
                created_at=existing.created_at if existing else datetime.now(timezone.utc),
                expires_at=expires_at,
                rotated_at=existing.rotated_at if existing else None,
                source=source,
                tags=tags if tags is not None else (existing.tags if existing else []),
            )
            self._cache[name] = entry
            self._persist(entry)
            event = "update" if existing else "create"
            self._audit(event, name, details=f"type={secret_type.value}")

    def rotate(self, name: str, new_value: str) -> bool:
        """Rotate a secret to a new value, recording the rotation timestamp.

        Logs the rotation event to Nexus (non-fatal on network failure).

        Args:
            name: Identifier of the secret to rotate.
            new_value: New plaintext value.

        Returns:
            True on success; False if the secret does not exist.
        """
        with self._lock:
            entry = self._cache.get(name)
            if entry is None:
                logger.warning("Cannot rotate unknown secret: '%s'", name)
                return False
            entry.value = new_value
            entry.rotated_at = datetime.now(timezone.utc)
            self._cache[name] = entry
            self._persist(entry)
            self._audit("rotate", name)

        # Log outside lock (network call)
        try:
            from engine.nexus.client import get_nexus_client

            get_nexus_client().add_entry(
                f"Secret Rotated: {name}",
                f"Secret '{name}' was rotated at "
                f"{datetime.now(timezone.utc).isoformat()}",
                content_type="note",
                category="security",
                tags=["secret", "rotation"],
            )
        except Exception as exc:
            logger.debug("Non-critical: Nexus rotation log failed: %s", exc)

        logger.info("Rotated secret: %s", name)
        return True

    def delete(self, name: str) -> bool:
        """Remove a secret from the vault.

        Args:
            name: Identifier of the secret to remove.

        Returns:
            True on success; False if the secret did not exist.
        """
        with self._lock:
            if name not in self._cache:
                return False
            del self._cache[name]
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("DELETE FROM secrets WHERE name = ?", (name,))
            self._audit("delete", name)
            return True

    def list_secrets(
        self,
        secret_type: Optional[SecretType] = None,
        tags: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """List secret metadata — secret values are never included.

        Args:
            secret_type: Optional filter by type.
            tags: Optional filter — entry must have at least one matching tag.

        Returns:
            List of metadata dicts (no ``value`` field).
        """
        with self._lock:
            results: List[Dict[str, Any]] = []
            for entry in self._cache.values():
                if secret_type and entry.secret_type != secret_type:
                    continue
                if tags and not any(t in entry.tags for t in tags):
                    continue
                results.append(
                    {
                        "name": entry.name,
                        "secret_type": entry.secret_type.value,
                        "source": entry.source.value,
                        "tags": entry.tags,
                        "created_at": entry.created_at.isoformat(),
                        "expires_at": (
                            entry.expires_at.isoformat() if entry.expires_at else None
                        ),
                        "rotated_at": (
                            entry.rotated_at.isoformat() if entry.rotated_at else None
                        ),
                        "is_expired": entry.is_expired(),
                    }
                )
            return results

    def load_from_env(self, prefix: str = "COSYSIM_") -> int:
        """Auto-import environment variables with the given prefix.

        Variables are imported with the prefix stripped and lowercased as
        the secret name (e.g. ``COSYSIM_LM_TOKEN`` → name ``lm_token``).

        Args:
            prefix: Environment variable prefix to scan.

        Returns:
            Number of secrets imported.
        """
        count = 0
        for key, value in os.environ.items():
            if key.startswith(prefix):
                secret_name = key[len(prefix):].lower()
                secret_type = _infer_secret_type(secret_name)
                self.set(
                    secret_name,
                    value,
                    secret_type=secret_type,
                    source=SecretSource.ENV_VAR,
                )
                count += 1
                logger.debug("Loaded secret from env: %s", secret_name)
        logger.info("Loaded %d secrets from env prefix '%s'", count, prefix)
        return count

    def load_from_config(self) -> int:
        """Scan the CosySim config for known secret keys and import them.

        Imports explicitly known keys first (``lmstudio.api_token``,
        ``nexus.api_key``), then scans the entire config tree for any key
        whose name looks like a secret.

        Returns:
            Number of secrets imported.
        """
        _KNOWN_SECRET_KEYS: Dict[str, SecretType] = {
            "lmstudio.api_token": SecretType.API_KEY,
            "nexus.api_key": SecretType.API_KEY,
        }
        count = 0
        try:
            from engine.config import get_config

            cfg = get_config()

            # Explicitly mapped keys
            for config_key, stype in _KNOWN_SECRET_KEYS.items():
                value = cfg.get(config_key)
                if value:
                    name = config_key.replace(".", "_")
                    if name not in self._cache:
                        self.set(name, str(value), secret_type=stype, source=SecretSource.CONFIG_FILE)
                        count += 1

            # Generic deep-scan
            def _scan(d: Dict[str, Any], prefix: str = "") -> None:
                nonlocal count
                for k, v in d.items():
                    full_key = f"{prefix}.{k}" if prefix else k
                    if isinstance(v, dict):
                        _scan(v, full_key)
                    elif isinstance(v, str) and v and _is_secret_key(k):
                        name = full_key.replace(".", "_")
                        if name not in self._cache:
                            stype = _infer_secret_type(k)
                            self.set(name, v, secret_type=stype, source=SecretSource.CONFIG_FILE)
                            count += 1

            _scan(cfg.get_all())
        except Exception as exc:
            logger.error("load_from_config failed: %s", exc)

        logger.info("Loaded %d secrets from config", count)
        return count

    def check_expiry(self) -> Dict[str, List[str]]:
        """Scan all secrets for expired or soon-to-expire entries.

        Alerts via Nexus when any issues are found (non-fatal).

        Returns:
            Dict with keys ``"expired"`` and ``"expiring_soon"``, each a
            list of secret names.
        """
        expired: List[str] = []
        expiring_soon: List[str] = []

        with self._lock:
            for entry in self._cache.values():
                if entry.is_expired():
                    expired.append(entry.name)
                elif entry.expires_soon(threshold_seconds=86400):  # 24 h
                    expiring_soon.append(entry.name)

        if expired or expiring_soon:
            try:
                from engine.nexus.client import get_nexus_client

                parts: List[str] = []
                if expired:
                    parts.append(f"EXPIRED: {', '.join(expired)}")
                if expiring_soon:
                    parts.append(f"EXPIRING SOON: {', '.join(expiring_soon)}")
                get_nexus_client().add_entry(
                    "Secret Expiry Alert",
                    ".  ".join(parts),
                    content_type="alert",
                    category="security",
                    tags=["secret", "expiry"],
                )
            except Exception as exc:
                logger.debug("Non-critical: Nexus expiry alert failed: %s", exc)

        return {"expired": expired, "expiring_soon": expiring_soon}

    def get_audit_log(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return the most recent audit log entries.

        Args:
            limit: Maximum number of rows to return.

        Returns:
            List of audit event dicts (newest first).
        """
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                "SELECT timestamp, event_type, secret_name, actor, details "
                "FROM secret_audit_log ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "timestamp": r[0],
                "event_type": r[1],
                "secret_name": r[2],
                "actor": r[3],
                "details": r[4],
            }
            for r in rows
        ]

    def export_safe_report(self) -> Dict[str, Any]:
        """Produce a metadata-only export suitable for health checks.

        Secret values are never included in the report.

        Returns:
            Dict with counts by type/source and full metadata list.
        """
        secrets = self.list_secrets()
        return {
            "total_secrets": len(secrets),
            "by_type": _count_by(secrets, "secret_type"),
            "by_source": _count_by(secrets, "source"),
            "expired_count": sum(1 for s in secrets if s["is_expired"]),
            "secrets": secrets,
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_manager_instance: Optional[SecretManager] = None
_manager_lock = threading.Lock()


def get_secret_manager() -> SecretManager:
    """Return the global SecretManager singleton.

    Returns:
        The module-level SecretManager instance (created on first call).
    """
    global _manager_instance
    if _manager_instance is None:
        with _manager_lock:
            if _manager_instance is None:
                _manager_instance = SecretManager()
    return _manager_instance
