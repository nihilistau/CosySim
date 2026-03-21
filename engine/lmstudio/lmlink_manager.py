"""
LMLinkManager — Multi-instance LMStudio federation

LMLink connects multiple LMStudio instances (local + remote via Tailscale)
so CosySim can route requests to the best available peer based on model
affinity, capability, load, and failover rules.

Configuration lives in ``config/lmlink.yaml``.

Usage::

    from engine.lmstudio.lmlink_manager import get_lmlink_manager

    mgr = get_lmlink_manager()
    if mgr.enabled:
        peer = mgr.resolve_peer("qwen3-0.6b")
        models = mgr.list_remote_models()
        status = mgr.get_status()
"""
from __future__ import annotations

import fnmatch
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Peer descriptor ────────────────────────────────────────────────────

@dataclass
class LMLinkPeer:
    """Represents an LMStudio instance (local or remote)."""

    name: str
    host: str
    port: int = 1234
    capabilities: List[str] = field(default_factory=lambda: ["inference"])
    max_models: int = 4
    max_context: int = 16384
    priority: int = 1
    tags: List[str] = field(default_factory=list)
    is_local: bool = False

    # Runtime state
    reachable: bool = False
    loaded_models: List[str] = field(default_factory=list)
    last_check: float = 0.0
    consecutive_failures: int = 0
    total_requests: int = 0
    total_errors: int = 0
    avg_latency_ms: float = 0.0

    @property
    def api_base(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def healthy(self) -> bool:
        return self.reachable and self.consecutive_failures < 3

    @property
    def error_rate(self) -> float:
        total = self.total_requests + self.total_errors
        return self.total_errors / total if total > 0 else 0.0

    def record_success(self, latency_ms: float) -> None:
        self.total_requests += 1
        self.consecutive_failures = 0
        # Exponential moving average for latency
        alpha = 0.2
        self.avg_latency_ms = (
            alpha * latency_ms + (1 - alpha) * self.avg_latency_ms
            if self.avg_latency_ms > 0
            else latency_ms
        )

    def record_failure(self) -> None:
        self.total_errors += 1
        self.consecutive_failures += 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "host": self.host,
            "port": self.port,
            "api_base": self.api_base,
            "capabilities": self.capabilities,
            "max_models": self.max_models,
            "max_context": self.max_context,
            "priority": self.priority,
            "tags": self.tags,
            "is_local": self.is_local,
            "reachable": self.reachable,
            "healthy": self.healthy,
            "loaded_models": self.loaded_models,
            "consecutive_failures": self.consecutive_failures,
            "total_requests": self.total_requests,
            "total_errors": self.total_errors,
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "error_rate": round(self.error_rate, 3),
        }


# ── Affinity rule ──────────────────────────────────────────────────────

@dataclass
class AffinityRule:
    """Maps model name patterns to preferred peers."""

    pattern: str
    prefer: str

    def matches(self, model_key: str) -> bool:
        """Check if a model key matches this affinity rule."""
        return fnmatch.fnmatch(model_key.lower(), self.pattern.lower())


# ── Routing result ─────────────────────────────────────────────────────

@dataclass
class RoutingDecision:
    """Result of a model routing decision."""

    peer: LMLinkPeer
    model_key: str
    reason: str
    fallback_peers: List[LMLinkPeer] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "peer": self.peer.name,
            "api_base": self.peer.api_base,
            "model_key": self.model_key,
            "reason": self.reason,
            "fallback_peers": [p.name for p in self.fallback_peers],
        }


# ── LMLink Manager ────────────────────────────────────────────────────

class LMLinkManager:
    """
    Federation manager for multi-instance LMStudio routing.

    Reads ``config/lmlink.yaml``, maintains peer health, and resolves
    the best peer for a given model request.
    """

    def __init__(self, config: Any = None) -> None:
        if config is None:
            from engine.config import get_config
            config = get_config()

        self._config = config
        self._lock = threading.Lock()

        # Parse config
        self._enabled: bool = bool(config.get("lmlink.enabled", False))
        self._strategy: str = str(
            config.get("lmlink.routing.strategy", "capability_first")
        )

        # Build peer list
        self._peers: Dict[str, LMLinkPeer] = {}
        self._affinity_rules: List[AffinityRule] = []
        self._load_config(config)

        # Failover config
        self._failover_enabled: bool = bool(
            config.get("lmlink.routing.failover.enabled", True)
        )
        self._max_retries: int = int(
            config.get("lmlink.routing.failover.max_retries", 2)
        )
        self._retry_delay_ms: int = int(
            config.get("lmlink.routing.failover.retry_delay_ms", 1000)
        )
        self._fallback_to_local: bool = bool(
            config.get("lmlink.routing.failover.fallback_to_local", True)
        )

        # Health monitoring
        self._health_interval: float = float(
            config.get("lmlink.health.check_interval_seconds", 60)
        )
        self._health_timeout_ms: int = int(
            config.get("lmlink.health.timeout_ms", 5000)
        )
        self._auto_reconnect: bool = bool(
            config.get("lmlink.health.auto_reconnect", True)
        )
        self._max_reconnect: int = int(
            config.get("lmlink.health.max_reconnect_attempts", 3)
        )

        # Background health thread
        self._health_thread: Optional[threading.Thread] = None
        self._health_stop = threading.Event()

        # Metrics
        self._routing_decisions: int = 0
        self._affinity_hits: int = 0
        self._failovers: int = 0

        if self._enabled:
            logger.info(
                "LMLinkManager initialized: %d peers, strategy=%s",
                len(self._peers), self._strategy,
            )
        else:
            logger.info("LMLink federation disabled")

    def _load_config(self, config: Any) -> None:
        """Parse peers and affinity rules from config."""
        # Local instance
        local_name = str(config.get("lmlink.local.name", "workstation"))
        local_host = str(config.get("lmlink.local.host", "localhost"))
        local_port = int(config.get("lmlink.local.port", 1234))
        local_caps = config.get("lmlink.local.capabilities", ["inference"])
        if isinstance(local_caps, str):
            local_caps = [local_caps]

        self._peers[local_name] = LMLinkPeer(
            name=local_name,
            host=local_host,
            port=local_port,
            capabilities=local_caps,
            is_local=True,
            priority=1,
            reachable=True,
        )

        # Remote peers
        peers_config = config.get("lmlink.peers", [])
        if isinstance(peers_config, list):
            for pc in peers_config:
                if not isinstance(pc, dict):
                    continue
                name = pc.get("name", "")
                host = pc.get("host", "")
                if not name or not host:
                    logger.warning("Skipping peer with missing name or host: %s", pc)
                    continue

                caps = pc.get("capabilities", ["inference"])
                if isinstance(caps, str):
                    caps = [caps]
                tags = pc.get("tags", [])
                if isinstance(tags, str):
                    tags = [tags]

                self._peers[name] = LMLinkPeer(
                    name=name,
                    host=host,
                    port=int(pc.get("port", 1234)),
                    capabilities=caps,
                    max_models=int(pc.get("max_models", 2)),
                    max_context=int(pc.get("max_context", 8192)),
                    priority=int(pc.get("priority", 2)),
                    tags=tags,
                    is_local=False,
                )

        # Affinity rules
        affinity_config = config.get("lmlink.routing.affinity", [])
        if isinstance(affinity_config, list):
            for ac in affinity_config:
                if isinstance(ac, dict):
                    pattern = ac.get("pattern", "")
                    prefer = ac.get("prefer", "")
                    if pattern and prefer:
                        self._affinity_rules.append(
                            AffinityRule(pattern=pattern, prefer=prefer)
                        )

    @property
    def enabled(self) -> bool:
        """Whether LMLink federation is enabled."""
        return self._enabled

    @property
    def strategy(self) -> str:
        """Current routing strategy."""
        return self._strategy

    # ── Peer management ──────────────────────────────────────────────

    def get_peer(self, name: str) -> Optional[LMLinkPeer]:
        """Get a peer by name."""
        return self._peers.get(name)

    def get_local_peer(self) -> Optional[LMLinkPeer]:
        """Get the local LMStudio instance."""
        for peer in self._peers.values():
            if peer.is_local:
                return peer
        return None

    def get_remote_peers(self) -> List[LMLinkPeer]:
        """Get all remote peers."""
        return [p for p in self._peers.values() if not p.is_local]

    def get_healthy_peers(self) -> List[LMLinkPeer]:
        """Get all healthy (reachable) peers."""
        return [p for p in self._peers.values() if p.healthy]

    # ── Model routing ────────────────────────────────────────────────

    def resolve_peer(
        self,
        model_key: str,
        *,
        require_capability: Optional[str] = None,
        exclude_peers: Optional[List[str]] = None,
    ) -> Optional[RoutingDecision]:
        """
        Resolve the best peer for a model request.

        Checks affinity rules first, then applies the routing strategy.

        Parameters
        ----------
        model_key : str
            The model to route.
        require_capability : str, optional
            Required capability (e.g., "vision", "embedding").
        exclude_peers : list[str], optional
            Peer names to exclude (for failover).

        Returns
        -------
        RoutingDecision or None
            The routing decision, or None if no peer is available.
        """
        if not self._enabled:
            # Return local peer when disabled
            local = self.get_local_peer()
            if local:
                return RoutingDecision(
                    peer=local,
                    model_key=model_key,
                    reason="lmlink_disabled_local_default",
                )
            return None

        self._routing_decisions += 1
        excluded = set(exclude_peers or [])

        # Filter candidates
        candidates = [
            p for p in self._peers.values()
            if p.healthy and p.name not in excluded
        ]

        # Filter by capability
        if require_capability:
            candidates = [
                p for p in candidates
                if require_capability in p.capabilities
            ]

        if not candidates:
            logger.warning("No healthy peers available for model '%s'", model_key)
            return None

        # Check affinity rules first
        for rule in self._affinity_rules:
            if rule.matches(model_key):
                preferred = next(
                    (p for p in candidates if p.name == rule.prefer), None
                )
                if preferred:
                    self._affinity_hits += 1
                    fallbacks = [p for p in candidates if p != preferred]
                    return RoutingDecision(
                        peer=preferred,
                        model_key=model_key,
                        reason=f"affinity_rule:{rule.pattern}→{rule.prefer}",
                        fallback_peers=fallbacks,
                    )

        # Apply routing strategy
        selected = self._apply_strategy(candidates, model_key)
        if selected:
            fallbacks = [p for p in candidates if p != selected]
            return RoutingDecision(
                peer=selected,
                model_key=model_key,
                reason=f"strategy:{self._strategy}",
                fallback_peers=fallbacks,
            )

        return None

    def _apply_strategy(
        self, candidates: List[LMLinkPeer], model_key: str
    ) -> Optional[LMLinkPeer]:
        """Apply the configured routing strategy to candidate peers."""
        if not candidates:
            return None

        if self._strategy == "local_first":
            # Prefer local, then by priority
            local = [p for p in candidates if p.is_local]
            if local:
                return local[0]
            return min(candidates, key=lambda p: p.priority)

        elif self._strategy == "round_robin":
            # Rotate through peers by total request count
            return min(candidates, key=lambda p: p.total_requests)

        elif self._strategy == "least_loaded":
            # Prefer peer with fewest loaded models
            return min(candidates, key=lambda p: len(p.loaded_models))

        elif self._strategy == "capability_first":
            # Check if model is already loaded on any peer
            for peer in sorted(candidates, key=lambda p: p.priority):
                if any(model_key in m for m in peer.loaded_models):
                    return peer
            # Otherwise, by priority
            return min(candidates, key=lambda p: p.priority)

        else:
            # Default: priority-based
            return min(candidates, key=lambda p: p.priority)

    # ── Remote model queries ─────────────────────────────────────────

    def list_remote_models(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Query all remote peers for their loaded models.

        Returns
        -------
        dict
            Mapping of peer name → list of loaded model info dicts.
        """
        result: Dict[str, List[Dict[str, Any]]] = {}

        for peer in self.get_remote_peers():
            if not peer.healthy:
                result[peer.name] = []
                continue

            try:
                models = self._query_peer_models(peer)
                peer.loaded_models = [
                    m.get("id", m.get("path", "")) for m in models
                ]
                result[peer.name] = models
            except Exception as e:
                logger.warning("Failed to query models from '%s': %s", peer.name, e)
                peer.record_failure()
                result[peer.name] = []

        return result

    # v1.44.0 [2026-03-21] — Build peer auth from config (peers may have different tokens)
    def _peer_headers(self, peer: LMLinkPeer) -> Dict[str, str]:
        """Build auth headers for a peer from config."""
        headers: Dict[str, str] = {}
        try:
            token = self._config.get("lmstudio.api_token", "")
            if token:
                headers["Authorization"] = f"Bearer {token}"
        except Exception:
            pass
        return headers

    def _query_peer_models(self, peer: LMLinkPeer) -> List[Dict[str, Any]]:
        """Query a remote peer for its loaded models via REST API."""
        import httpx

        url = f"{peer.api_base}/api/v1/models"
        timeout = self._health_timeout_ms / 1000

        try:
            resp = httpx.get(url, headers=self._peer_headers(peer), timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            return data.get("data", [])
        except Exception as e:
            raise RuntimeError(f"Failed to query {peer.name}: {e}") from e

    # ── Health monitoring ────────────────────────────────────────────

    def check_peer_health(self, peer: LMLinkPeer) -> bool:
        """
        Check if a peer is reachable.

        Uses a lightweight GET /api/v1/models request.
        """
        import httpx

        url = f"{peer.api_base}/api/v1/models"
        timeout = self._health_timeout_ms / 1000

        try:
            resp = httpx.get(url, headers=self._peer_headers(peer), timeout=timeout)
            peer.reachable = resp.status_code == 200
            peer.last_check = time.time()
            peer.consecutive_failures = 0 if peer.reachable else peer.consecutive_failures
            return peer.reachable
        except Exception:
            peer.reachable = False
            peer.last_check = time.time()
            peer.consecutive_failures += 1
            return False

    def check_all_peers(self) -> Dict[str, bool]:
        """Check health of all peers. Returns {name: reachable}."""
        results = {}
        for peer in self._peers.values():
            if peer.is_local:
                # Local check via CLI
                try:
                    from engine.lmstudio.client import get_lmstudio_manager
                    peer.reachable = get_lmstudio_manager().is_server_running()
                except Exception:
                    peer.reachable = False
                peer.last_check = time.time()
                results[peer.name] = peer.reachable
            else:
                results[peer.name] = self.check_peer_health(peer)

        return results

    def start_health_monitoring(self) -> None:
        """Start background health check thread for all peers."""
        if not self._enabled:
            return
        if self._health_thread is not None and self._health_thread.is_alive():
            return

        self._health_stop.clear()
        self._health_thread = threading.Thread(
            target=self._health_loop,
            name="lmlink-health-monitor",
            daemon=True,
        )
        self._health_thread.start()
        logger.info("Started LMLink health monitoring (interval=%ds)", self._health_interval)

    def stop_health_monitoring(self) -> None:
        """Stop background health monitoring."""
        self._health_stop.set()
        if self._health_thread is not None:
            self._health_thread.join(timeout=5)
            self._health_thread = None

    def _health_loop(self) -> None:
        """Background thread: check all peers periodically."""
        while not self._health_stop.is_set():
            try:
                self.check_all_peers()
            except Exception:
                logger.debug("LMLink health check error", exc_info=True)

            self._health_stop.wait(self._health_interval)

    # ── Failover ─────────────────────────────────────────────────────

    def resolve_with_failover(
        self,
        model_key: str,
        *,
        require_capability: Optional[str] = None,
    ) -> Optional[RoutingDecision]:
        """
        Resolve a peer with automatic failover.

        Tries the primary decision first, then falls back through
        the fallback peers up to max_retries.
        """
        if not self._failover_enabled:
            return self.resolve_peer(model_key, require_capability=require_capability)

        excluded: List[str] = []
        for attempt in range(1 + self._max_retries):
            decision = self.resolve_peer(
                model_key,
                require_capability=require_capability,
                exclude_peers=excluded,
            )

            if decision is None:
                break

            if decision.peer.healthy:
                if attempt > 0:
                    self._failovers += 1
                    logger.info(
                        "LMLink failover: %s → %s (attempt %d)",
                        model_key, decision.peer.name, attempt + 1,
                    )
                return decision

            excluded.append(decision.peer.name)

            if attempt < self._max_retries:
                time.sleep(self._retry_delay_ms / 1000)

        # Final fallback: local
        if self._fallback_to_local:
            local = self.get_local_peer()
            if local:
                self._failovers += 1
                return RoutingDecision(
                    peer=local,
                    model_key=model_key,
                    reason="fallback_to_local",
                )

        return None

    # ── Status and metrics ───────────────────────────────────────────

    def get_status(self) -> Dict[str, Any]:
        """Get comprehensive LMLink status."""
        return {
            "enabled": self._enabled,
            "strategy": self._strategy,
            "peers": {
                name: peer.to_dict() for name, peer in self._peers.items()
            },
            "affinity_rules": [
                {"pattern": r.pattern, "prefer": r.prefer}
                for r in self._affinity_rules
            ],
            "failover": {
                "enabled": self._failover_enabled,
                "max_retries": self._max_retries,
                "fallback_to_local": self._fallback_to_local,
            },
            "metrics": {
                "routing_decisions": self._routing_decisions,
                "affinity_hits": self._affinity_hits,
                "failovers": self._failovers,
            },
        }

    # ── Shutdown ─────────────────────────────────────────────────────

    def shutdown(self) -> None:
        """Clean shutdown."""
        self.stop_health_monitoring()
        logger.info("LMLinkManager shut down")


# ── Singleton ────────────────────────────────────────────────────────────

_instance: Optional[LMLinkManager] = None
_instance_lock = threading.Lock()


def get_lmlink_manager(config: Any = None) -> LMLinkManager:
    """Return the global LMLinkManager singleton."""
    global _instance
    if _instance is not None:
        return _instance

    with _instance_lock:
        if _instance is not None:
            return _instance
        _instance = LMLinkManager(config=config)
        return _instance
