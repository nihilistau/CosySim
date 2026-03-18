"""
Security MCP Skills for CosySim.

Pack: ``security`` — 10 skills split between secret management (5) and
rate limiting (5), all in the ``system`` category.
"""

import json
import logging

from engine.skills.skill import skill

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lazy accessors (avoid circular imports at module load time)
# ---------------------------------------------------------------------------


def _get_sm():
    """Return the global SecretManager singleton."""
    from engine.security.secret_manager import get_secret_manager

    return get_secret_manager()


def _get_rl():
    """Return the global RateLimiter singleton."""
    from engine.security.rate_limiter import get_rate_limiter

    return get_rate_limiter()


# ---------------------------------------------------------------------------
# Secret management skills
# ---------------------------------------------------------------------------


@skill(
    pack="security",
    description=(
        "List metadata for all secrets in the vault, or inspect a single "
        "named secret.  Secret values are NEVER returned — metadata only "
        "(type, source, tags, expiry)."
    ),
    category="system",
    tags=["security", "secrets"],
    cooldown=2.0,
)
def get_secret_status(name: str = "") -> str:
    """Get secret metadata — values are never exposed.

    Args:
        name: Optional secret name.  If omitted, returns a full vault report.

    Returns:
        JSON string with metadata or vault health report.
    """
    sm = _get_sm()
    if name:
        secrets = sm.list_secrets()
        entry = next((s for s in secrets if s["name"] == name), None)
        if entry is None:
            return json.dumps({"error": f"Secret '{name}' not found"})
        return json.dumps(entry)
    report = sm.export_safe_report()
    return json.dumps(report)


@skill(
    pack="security",
    description=(
        "Rotate a named secret to a new value.  The rotation timestamp is "
        "updated, an audit event is written, and the event is logged to Nexus."
    ),
    category="system",
    tags=["security", "secrets", "rotation"],
    cooldown=5.0,
)
def rotate_secret(name: str, new_value: str) -> str:
    """Rotate a secret value and record the event.

    Args:
        name: Identifier of the secret to rotate.
        new_value: Replacement plaintext value.

    Returns:
        JSON string indicating success or an error message.
    """
    sm = _get_sm()
    success = sm.rotate(name, new_value)
    if success:
        return json.dumps({"status": "ok", "rotated": name})
    return json.dumps({"status": "error", "message": f"Secret '{name}' not found"})


@skill(
    pack="security",
    description=(
        "Scan all secrets for expired entries or those expiring within 24 "
        "hours.  Returns lists of affected secret names and triggers a Nexus "
        "alert when issues are found."
    ),
    category="system",
    tags=["security", "secrets", "expiry"],
    cooldown=10.0,
)
def check_secret_expiry() -> str:
    """Check for expired or expiring-soon secrets.

    Returns:
        JSON string with ``expired`` and ``expiring_soon`` lists.
    """
    sm = _get_sm()
    result = sm.check_expiry()
    return json.dumps(result)


@skill(
    pack="security",
    description=(
        "Import all COSYSIM_ prefixed environment variables into the secret "
        "vault right now.  Returns the number of secrets loaded."
    ),
    category="system",
    tags=["security", "secrets", "env"],
    cooldown=30.0,
)
def load_secrets_from_env() -> str:
    """Trigger environment variable import into the vault.

    Returns:
        JSON string with status and count of loaded secrets.
    """
    sm = _get_sm()
    count = sm.load_from_env()
    return json.dumps({"status": "ok", "loaded": count})


@skill(
    pack="security",
    description=(
        "Return the most recent entries from the secret audit log, showing "
        "who accessed, created, rotated, or deleted each secret and when."
    ),
    category="system",
    tags=["security", "secrets", "audit"],
    cooldown=2.0,
)
def get_secret_audit_log(limit: int = 20) -> str:
    """Return recent audit log entries.

    Args:
        limit: Maximum number of rows to return (default 20).

    Returns:
        JSON array of audit events (newest first).
    """
    sm = _get_sm()
    entries = sm.get_audit_log(limit=limit)
    return json.dumps(entries)


# ---------------------------------------------------------------------------
# Rate limiting skills
# ---------------------------------------------------------------------------


@skill(
    pack="security",
    description=(
        "Show current token levels, queue depth, and rejection rates for all "
        "rate-limited services, or for a single named service."
    ),
    category="system",
    tags=["security", "rate_limit"],
    cooldown=1.0,
)
def get_rate_limit_status(service: str = "") -> str:
    """Get rate limit status for all or one service.

    Args:
        service: Optional service name.  If omitted, returns all services.

    Returns:
        JSON string with current status snapshot.
    """
    rl = _get_rl()
    if service:
        return json.dumps(rl.get_status(service))
    return json.dumps(rl.get_metrics())


@skill(
    pack="security",
    description=(
        "Update the token bucket capacity and refill rate for a named service.  "
        "Changes take effect immediately and persist across restarts."
    ),
    category="system",
    tags=["security", "rate_limit", "config"],
    cooldown=5.0,
)
def configure_rate_limit(service: str, capacity: float, refill_rate: float) -> str:
    """Update a service's rate limit configuration.

    Args:
        service: Service identifier to configure.
        capacity: New maximum token capacity.
        refill_rate: New token refill rate (tokens per second).

    Returns:
        JSON string confirming the new configuration.
    """
    from engine.security.rate_limiter import RateLimitConfig

    rl = _get_rl()
    config = RateLimitConfig(
        service_name=service, capacity=capacity, refill_rate=refill_rate
    )
    rl.configure_service(config)
    return json.dumps(
        {
            "status": "ok",
            "service": service,
            "capacity": capacity,
            "refill_rate": refill_rate,
        }
    )


@skill(
    pack="security",
    description=(
        "Reset a service's token bucket to full capacity immediately.  "
        "Useful after a maintenance window or emergency situation."
    ),
    category="system",
    tags=["security", "rate_limit", "admin"],
    cooldown=5.0,
)
def reset_rate_limit(service: str) -> str:
    """Reset a service's token bucket to full capacity.

    Args:
        service: Service identifier to reset.

    Returns:
        JSON string confirming the reset.
    """
    rl = _get_rl()
    rl.release_all(service)
    return json.dumps(
        {
            "status": "ok",
            "service": service,
            "message": "Bucket reset to full capacity",
        }
    )


@skill(
    pack="security",
    description=(
        "Return aggregate metrics for all rate-limited services: total calls, "
        "rejection counts, rejection rate, and average wait time."
    ),
    category="system",
    tags=["security", "rate_limit", "metrics"],
    cooldown=2.0,
)
def get_rate_metrics() -> str:
    """Get aggregate metrics for all rate-limited services.

    Returns:
        JSON object mapping service name to metrics dict.
    """
    rl = _get_rl()
    metrics = rl.get_metrics()
    return json.dumps(metrics)


@skill(
    pack="security",
    description=(
        "List all services currently under backpressure — i.e. where the "
        "token level has dropped below the configured threshold, signalling "
        "producers to slow down."
    ),
    category="system",
    tags=["security", "rate_limit", "backpressure"],
    cooldown=2.0,
)
def check_backpressure() -> str:
    """Check which services are currently under backpressure.

    Returns:
        JSON string with count and list of services under backpressure.
    """
    rl = _get_rl()
    services_under_pressure = []
    for service in list(rl._buckets.keys()):
        if rl.backpressure_active(service):
            services_under_pressure.append(rl.get_status(service))
    return json.dumps(
        {
            "backpressure_count": len(services_under_pressure),
            "services": services_under_pressure,
        }
    )
