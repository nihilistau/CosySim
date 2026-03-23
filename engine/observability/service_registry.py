"""Service Registry — dynamic service discovery for CosySim scenes and agents.

Provides a singleton ServiceRegistry where services self-register and can be
discovered by type, capability, or tag.  Built-in system services are
auto-registered on import.

Usage::

    from engine.observability.service_registry import get_service_registry, ServiceRecord, ServiceType

    registry = get_service_registry()
    result   = registry.discover(capabilities=["inference"])
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = "data/service_registry.db"


# ---------------------------------------------------------------------------
# Enums and dataclasses
# ---------------------------------------------------------------------------


class ServiceType(Enum):
    """Classification of a registered service."""

    SCENE = "scene"
    AGENT = "agent"
    LLM = "llm"
    SKILL_PACK = "skill_pack"
    TOOL = "tool"
    EXTERNAL = "external"


@dataclass
class ServiceRecord:
    """Complete record for a registered service.

    Attributes:
        service_id: Unique identifier (generated on first registration).
        name: Human-readable service name.
        service_type: ServiceType enum value.
        host: Hostname or IP.
        port: TCP port (0 if not applicable).
        health_url: URL for health checks (empty string if N/A).
        metadata: Arbitrary key/value metadata.
        registered_at: When the service first registered.
        last_seen: Timestamp of most recent heartbeat or registration.
        status: ``"active"``, ``"unknown"``, or ``"inactive"``.
        tags: List of descriptive tags.
        capabilities: List of capability strings (used for discovery).
    """

    service_id: str
    name: str
    service_type: ServiceType
    host: str
    port: int
    health_url: str
    metadata: Dict[str, Any]
    registered_at: datetime
    last_seen: datetime
    status: str
    tags: List[str]
    capabilities: List[str]


@dataclass
class DiscoveryResult:
    """Result from a service discovery query.

    Attributes:
        services: Matching service records.
        total: Total count of matching records.
        filtered_by: Filters that were applied.
    """

    services: List[ServiceRecord]
    total: int
    filtered_by: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Built-in service definitions
# ---------------------------------------------------------------------------

_BUILTIN_SERVICES: List[Dict[str, Any]] = [
    {
        "service_id": "builtin-lmstudio",
        "name": "lmstudio",
        "service_type": ServiceType.LLM,
        "host": "localhost",
        "port": 1234,
        "health_url": "",  # resolved lazily via _resolve_health_url
        "metadata": {"description": "LMStudio local LLM inference server"},
        "tags": ["llm", "inference", "local"],
        "capabilities": ["inference", "embeddings", "vision"],
    },
    {
        "service_id": "builtin-nexus",
        "name": "nexus",
        "service_type": ServiceType.TOOL,
        "host": "localhost",
        "port": 0,
        "health_url": "",
        "metadata": {"description": "Nexus knowledge base and Q&A cache"},
        "tags": ["knowledge", "qa", "search"],
        "capabilities": ["knowledge", "search", "qa"],
    },
    {
        "service_id": "builtin-scheduler",
        "name": "scheduler",
        "service_type": ServiceType.TOOL,
        "host": "localhost",
        "port": 0,
        "health_url": "",
        "metadata": {"description": "Task scheduler for recurring jobs"},
        "tags": ["scheduling", "cron"],
        "capabilities": ["scheduling", "cron"],
    },
    {
        "service_id": "builtin-secret_manager",
        "name": "secret_manager",
        "service_type": ServiceType.TOOL,
        "host": "localhost",
        "port": 0,
        "health_url": "",
        "metadata": {"description": "Secure secret management"},
        "tags": ["security", "secrets"],
        "capabilities": ["secrets", "vault"],
    },
    {
        "service_id": "builtin-rate_limiter",
        "name": "rate_limiter",
        "service_type": ServiceType.TOOL,
        "host": "localhost",
        "port": 0,
        "health_url": "",
        "metadata": {"description": "Rate limiting and backpressure"},
        "tags": ["security", "rate_limiting"],
        "capabilities": ["rate_limiting", "backpressure"],
    },
    {
        "service_id": "builtin-structured_logger",
        "name": "structured_logger",
        "service_type": ServiceType.TOOL,
        "host": "localhost",
        "port": 0,
        "health_url": "",
        "metadata": {"description": "Queryable structured logging with SQLite backend"},
        "tags": ["logging", "observability"],
        "capabilities": ["logging", "tracing"],
    },
]


# ---------------------------------------------------------------------------
# ServiceRegistry
# ---------------------------------------------------------------------------


class ServiceRegistry:
    """Dynamic registry for CosySim service discovery.

    Services self-register via :meth:`register` and publish heartbeats via
    :meth:`heartbeat`.  Callers discover services via :meth:`discover`.

    Instantiate via :func:`get_service_registry` (singleton).
    """

    def __init__(self, db_path: str = _DEFAULT_DB_PATH) -> None:
        """Initialise the ServiceRegistry.

        Args:
            db_path: Path to SQLite backing store.
        """
        self._db_path = db_path
        self._lock = threading.RLock()
        self._services: Dict[str, ServiceRecord] = {}
        self._callbacks: Dict[str, List[Callable]] = {}
        self._init_db()
        self._load_from_db()
        self._register_builtins()

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        """Create the services table in SQLite if absent."""
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS services (
                    service_id        TEXT PRIMARY KEY,
                    name              TEXT NOT NULL,
                    service_type      TEXT NOT NULL,
                    host              TEXT NOT NULL,
                    port              INTEGER NOT NULL,
                    health_url        TEXT,
                    metadata_json     TEXT,
                    registered_at     TEXT NOT NULL,
                    last_seen         TEXT NOT NULL,
                    status            TEXT NOT NULL DEFAULT 'active',
                    tags_json         TEXT,
                    capabilities_json TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_svc_type ON services (service_type)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_svc_status ON services (status)"
            )
            conn.commit()

    def _load_from_db(self) -> None:
        """Load all persisted service records from SQLite into memory."""
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute("SELECT * FROM services").fetchall()
            for row in rows:
                record = self._row_to_record(row)
                self._services[record.service_id] = record
        except Exception as exc:
            logger.warning("Failed to load service registry from DB: %s", exc)

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> ServiceRecord:
        """Convert a SQLite Row to a ServiceRecord.

        Args:
            row: Row from the ``services`` table.

        Returns:
            Populated ServiceRecord.
        """
        return ServiceRecord(
            service_id=row["service_id"],
            name=row["name"],
            service_type=ServiceType(row["service_type"]),
            host=row["host"],
            port=row["port"],
            health_url=row["health_url"] or "",
            metadata=json.loads(row["metadata_json"] or "{}"),
            registered_at=datetime.fromisoformat(row["registered_at"]),
            last_seen=datetime.fromisoformat(row["last_seen"]),
            status=row["status"],
            tags=json.loads(row["tags_json"] or "[]"),
            capabilities=json.loads(row["capabilities_json"] or "[]"),
        )

    def _persist_record(self, record: ServiceRecord) -> None:
        """Upsert a ServiceRecord to SQLite.

        Args:
            record: Record to persist.
        """
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO services
                        (service_id, name, service_type, host, port, health_url,
                         metadata_json, registered_at, last_seen, status,
                         tags_json, capabilities_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.service_id,
                        record.name,
                        record.service_type.value,
                        record.host,
                        record.port,
                        record.health_url,
                        json.dumps(record.metadata),
                        record.registered_at.isoformat(),
                        record.last_seen.isoformat(),
                        record.status,
                        json.dumps(record.tags),
                        json.dumps(record.capabilities),
                    ),
                )
                conn.commit()
        except Exception as exc:
            logger.warning("Failed to persist service record %s: %s", record.service_id, exc)

    def _delete_record(self, service_id: str) -> None:
        """Delete a service record from SQLite.

        Args:
            service_id: ID to delete.
        """
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("DELETE FROM services WHERE service_id = ?", (service_id,))
                conn.commit()
        except Exception as exc:
            logger.warning("Failed to delete service record %s: %s", service_id, exc)

    # ------------------------------------------------------------------
    # Built-in bootstrap
    # ------------------------------------------------------------------

    def _register_builtins(self) -> None:
        """Auto-register all built-in services if not already present."""
        from engine.port_registry import get_service_url

        now = datetime.now()
        for svc in _BUILTIN_SERVICES:
            sid = svc["service_id"]
            if sid not in self._services:
                health_url = svc["health_url"]
                if not health_url and svc["name"] == "lmstudio":
                    health_url = get_service_url("lmstudio", "/api/v1/models")
                record = ServiceRecord(
                    service_id=sid,
                    name=svc["name"],
                    service_type=svc["service_type"],
                    host=svc["host"],
                    port=svc["port"],
                    health_url=health_url,
                    metadata=svc["metadata"],
                    registered_at=now,
                    last_seen=now,
                    status="active",
                    tags=list(svc["tags"]),
                    capabilities=list(svc["capabilities"]),
                )
                self._services[sid] = record
                self._persist_record(record)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(self, record: ServiceRecord) -> str:
        """Add or update a service in the registry.

        If *record.service_id* already exists, only ``last_seen`` and mutable
        fields are updated; ``registered_at`` is preserved from the original.

        Args:
            record: ServiceRecord to register.

        Returns:
            The service_id of the registered (or updated) service.
        """
        with self._lock:
            if record.service_id in self._services:
                record.registered_at = self._services[record.service_id].registered_at
            record.last_seen = datetime.now()
            self._services[record.service_id] = record
            self._persist_record(record)
        logger.debug("Registered service: %s (%s)", record.name, record.service_id)
        return record.service_id

    def deregister(self, service_id: str) -> bool:
        """Remove a service from the registry.

        Args:
            service_id: ID of the service to remove.

        Returns:
            True if the service was found and removed, False otherwise.
        """
        with self._lock:
            if service_id not in self._services:
                return False
            del self._services[service_id]
            self._callbacks.pop(service_id, None)
            self._delete_record(service_id)
        logger.debug("Deregistered service: %s", service_id)
        return True

    def heartbeat(self, service_id: str) -> bool:
        """Update the ``last_seen`` timestamp for a registered service.

        Args:
            service_id: ID of the service sending the heartbeat.

        Returns:
            True if updated, False if the service is not registered.
        """
        with self._lock:
            if service_id not in self._services:
                return False
            self._services[service_id].last_seen = datetime.now()
            self._services[service_id].status = "active"
            self._persist_record(self._services[service_id])
        return True

    def discover(
        self,
        service_type: Optional[ServiceType] = None,
        tags: Optional[List[str]] = None,
        capabilities: Optional[List[str]] = None,
        status: Optional[str] = None,
    ) -> DiscoveryResult:
        """Find services matching the given filters.

        All supplied filters must match (AND semantics).  Tag and capability
        filters require *all* supplied values to be present in the record.

        Args:
            service_type: Filter by ServiceType.
            tags: Filter by tags (all must be present).
            capabilities: Filter by capabilities (all must be present).
            status: Filter by status string (e.g. ``"active"``).

        Returns:
            DiscoveryResult containing matched services.
        """
        with self._lock:
            results = list(self._services.values())

        filters_applied: Dict[str, Any] = {}

        if service_type is not None:
            results = [s for s in results if s.service_type == service_type]
            filters_applied["service_type"] = service_type.value

        if tags:
            results = [s for s in results if all(t in s.tags for t in tags)]
            filters_applied["tags"] = tags

        if capabilities:
            results = [s for s in results if all(c in s.capabilities for c in capabilities)]
            filters_applied["capabilities"] = capabilities

        if status:
            results = [s for s in results if s.status == status]
            filters_applied["status"] = status

        return DiscoveryResult(
            services=results,
            total=len(results),
            filtered_by=filters_applied,
        )

    def get(self, service_id: str) -> Optional[ServiceRecord]:
        """Retrieve a specific service by ID.

        Args:
            service_id: ID to look up.

        Returns:
            ServiceRecord if found, None otherwise.
        """
        with self._lock:
            return self._services.get(service_id)

    def list_all(self) -> List[ServiceRecord]:
        """Return all registered services.

        Returns:
            Snapshot list of all ServiceRecord objects.
        """
        with self._lock:
            return list(self._services.values())

    def expire_stale(self, max_age_seconds: float = 120.0) -> int:
        """Mark services that haven't sent a heartbeat recently as ``"unknown"``.

        Built-in services (IDs starting with ``"builtin-"``) are never expired.

        Args:
            max_age_seconds: Maximum age of ``last_seen`` before marking unknown
                (default 120 s).

        Returns:
            Number of services marked as unknown.
        """
        cutoff = datetime.now() - timedelta(seconds=max_age_seconds)
        count = 0
        with self._lock:
            for service_id, record in self._services.items():
                if service_id.startswith("builtin-"):
                    continue
                if record.status == "active" and record.last_seen < cutoff:
                    self._services[service_id].status = "unknown"
                    self._persist_record(self._services[service_id])
                    count += 1
                    logger.debug("Marked stale service as unknown: %s", record.name)
        return count

    def get_by_capability(self, capability: str) -> List[ServiceRecord]:
        """Find all services offering a specific capability.

        Args:
            capability: Capability string to search for.

        Returns:
            List of matching ServiceRecord objects.
        """
        with self._lock:
            return [s for s in self._services.values() if capability in s.capabilities]

    def broadcast_event(self, event_type: str, data: Any) -> int:
        """Notify all registered event-handler callbacks.

        Args:
            event_type: Event type identifier string.
            data: Arbitrary event payload passed to each callback.

        Returns:
            Number of callbacks that were successfully invoked.
        """
        with self._lock:
            callbacks_snapshot = {k: list(v) for k, v in self._callbacks.items()}

        notified = 0
        for service_id, callbacks in callbacks_snapshot.items():
            for callback in callbacks:
                try:
                    callback(event_type, data)
                    notified += 1
                except Exception as exc:
                    logger.warning("Callback error for service %s: %s", service_id, exc)
        return notified

    def register_callback(self, service_id: str, fn: Callable) -> None:
        """Register an event-handler callback for a service.

        Args:
            service_id: ID of the service registering the handler.
            fn: Callable ``(event_type: str, data: Any) -> None`` invoked
                on :meth:`broadcast_event`.
        """
        with self._lock:
            if service_id not in self._callbacks:
                self._callbacks[service_id] = []
            self._callbacks[service_id].append(fn)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_registry_instance: Optional[ServiceRegistry] = None
_registry_lock = threading.Lock()


def get_service_registry(db_path: str = _DEFAULT_DB_PATH) -> ServiceRegistry:
    """Return the global ServiceRegistry singleton.

    Args:
        db_path: SQLite file path (used only on first call).

    Returns:
        The module-level ServiceRegistry instance.
    """
    global _registry_instance
    if _registry_instance is None:
        with _registry_lock:
            if _registry_instance is None:
                _registry_instance = ServiceRegistry(db_path=db_path)
    return _registry_instance
