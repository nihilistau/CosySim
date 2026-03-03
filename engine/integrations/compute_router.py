"""Compute Router — routes inference requests across Colab tunnels, Colab AI agent, and LMStudio.

Tracks usage against per-account limits, detects account tiers, and provides
a unified interface for model inference regardless of backend.
"""
from __future__ import annotations

import json
import logging
import os
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from engine.integrations.google_account_pool import GoogleAccount

logger = logging.getLogger(__name__)

# ──── Constants ───────────────────────────────────────────────────────────────

MAX_JIT_SESSIONS = 3
JIT_CONFIG_PATH = Path("data") / "accounts" / "jit_config.json"

TIER_FREE_HARDWARE = ["T4", "V5E1"]
TIER_PRO_HARDWARE = ["H100", "G4", "A100", "L4", "V6E1"]

MODELS_FREE = [
    "gemini-2.0-flash-exp",
    "gemini-2.5-flash-exp",
    "gemini-1.5-flash",
    "gemma-3-1b-it",
    "gemma-3-4b-it",
]

MODELS_PRO = [
    "gemini-2.0-flash-exp",
    "gemini-2.5-flash-exp",
    "gemini-2.5-pro-exp",
    "gemini-3.1-pro",
    "gemini-1.5-pro",
    "gemma-3-27b-it",
    "text-embedding-004",
]

LIMITS_FREE: Dict[str, float] = {
    "colab_requests_per_day": 100,
    "colab_gpu_hours_per_day": 6.0,
    "nlm_queries_per_day": 50,
    "drive_storage_gb": 15.0,
}

LIMITS_PRO: Dict[str, float] = {
    "colab_requests_per_day": 1000,
    "colab_gpu_hours_per_day": 24.0,
    "nlm_queries_per_day": 500,
    "drive_storage_gb": 100.0,
}

# ──── Data model ──────────────────────────────────────────────────────────────


@dataclass
class AccountTier:
    """Per-account tier metadata and usage tracking.

    Attributes:
        account_name: Google account identifier.
        tier: "free", "pro", or "unknown".
        hardware: List of available GPU hardware strings.
        available_models: Models accessible at this tier.
        limits: Daily/storage limits keyed by service name.
        usage: Locally tracked usage counters keyed by service name.
    """

    account_name: str
    tier: str
    hardware: List[str]
    available_models: List[str]
    limits: Dict[str, float]
    usage: Dict[str, float]


class ComputeUnavailableError(Exception):
    """Raised when no compute backend is available for inference."""


# ──── JIT Session context manager ────────────────────────────────────────────


class JITSession:
    """Context manager for one-shot JIT Colab sessions.

    On enter, selects the best available session (existing tunnel or
    colab agent). On exit, the session reference is released — if a new
    tunnel was provisioned solely for this session it will be torn down.

    Args:
        router: ComputeRouter to route through.
        tier: Minimum account tier — ``"free"`` or ``"pro"``.

    Usage::

        with JITSession(router, tier="free") as sess:
            url = sess.tunnel_url  # may be None if using colab_agent
            result = router.jit_infer("hello")
    """

    def __init__(self, router: "ComputeRouter", tier: str = "free") -> None:
        self._router = router
        self._tier = tier
        self._session: Optional[Any] = None  # TunnelSession if acquired
        self._owned: bool = False  # True if we spawned this session

    def __enter__(self) -> Optional[Any]:
        """Acquire the best available session.

        Returns:
            A ``TunnelSession`` if a healthy tunnel exists, else ``None``.
        """
        try:
            from engine.integrations.colab_tunnel_server import get_tunnel_server
            server = get_tunnel_server()
            healthy = [s for s in server._sessions.values() if s.healthy]
            if healthy:
                self._session = healthy[0]
                self._owned = False
                return self._session
        except Exception as exc:
            logger.debug("JITSession: could not acquire tunnel: %s", exc)
        return None

    def __exit__(self, *args: Any) -> None:
        """Release or tear down the session.

        Owned sessions (provisioned solely for this JIT call) are torn down.
        Borrowed sessions are left running.
        """
        if self._owned and self._session is not None:
            try:
                from engine.integrations.colab_tunnel_server import get_tunnel_server
                server = get_tunnel_server()
                key = self._session.account_name
                if key in server._sessions:
                    del server._sessions[key]
                    logger.debug("JITSession: torn down session for %s", key)
            except Exception as exc:
                logger.debug("JITSession: teardown error: %s", exc)
        self._session = None
        self._owned = False



# ──── Router ──────────────────────────────────────────────────────────────────


class ComputeRouter:
    """Routes inference requests to the best available compute backend.

    Priority order: active Colab tunnels → Colab AI agent → local LMStudio.
    Tracks per-account usage against configurable limits.
    """

    def __init__(self) -> None:
        self._tiers: Dict[str, AccountTier] = {}
        self._feature_config: Dict[str, Dict[str, Any]] = {}
        self._custom_limits: Dict[str, Dict[str, float]] = {}
        self._usage: Dict[str, Dict[str, float]] = {}
        self._active_jit_sessions: int = 0
        self._jit_config: Dict[str, Any] = {
            "max_session_minutes": 25,
            "idle_timeout_minutes": 5,
            "human_delays": True,
            "min_delay_s": 0.5,
            "max_delay_s": 2.5,
        }
        self._load_jit_config()

    # ──── JIT config ──────────────────────────────────────────────────────────

    def _load_jit_config(self) -> None:
        """Load persisted JIT config from disk if present."""
        try:
            if JIT_CONFIG_PATH.exists():
                with JIT_CONFIG_PATH.open("r", encoding="utf-8") as fh:
                    stored = json.load(fh)
                self._jit_config.update(stored)
        except Exception as exc:
            logger.debug("Could not load JIT config: %s", exc)

    def configure_jit(
        self,
        max_session_minutes: int = 25,
        idle_timeout_minutes: int = 5,
        human_delays: bool = True,
        min_delay_s: float = 0.5,
        max_delay_s: float = 2.5,
    ) -> None:
        """Configure JIT compute behaviour and persist to disk.

        Args:
            max_session_minutes: Maximum JIT session lifetime (Colab free tier limit).
            idle_timeout_minutes: Minutes of inactivity before auto-teardown.
            human_delays: Whether to add random human-like delays between requests.
            min_delay_s: Minimum random delay in seconds.
            max_delay_s: Maximum random delay in seconds.
        """
        self._jit_config.update(
            {
                "max_session_minutes": max_session_minutes,
                "idle_timeout_minutes": idle_timeout_minutes,
                "human_delays": human_delays,
                "min_delay_s": min_delay_s,
                "max_delay_s": max_delay_s,
            }
        )
        try:
            JIT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with JIT_CONFIG_PATH.open("w", encoding="utf-8") as fh:
                json.dump(self._jit_config, fh, indent=2)
        except Exception as exc:
            logger.warning("Could not persist JIT config: %s", exc)
        logger.info(
            "JIT config updated: max=%dmin idle=%dmin delays=%s",
            max_session_minutes,
            idle_timeout_minutes,
            human_delays,
        )

    def _jit_human_delay(self) -> None:
        """Sleep a random human-like interval if human_delays is enabled."""
        if not self._jit_config.get("human_delays", True):
            return
        delay = random.uniform(
            float(self._jit_config.get("min_delay_s", 0.5)),
            float(self._jit_config.get("max_delay_s", 2.5)),
        )
        time.sleep(delay)

    # ──── JIT inference / execution ───────────────────────────────────────────

    def jit_infer(
        self,
        prompt: str,
        model: str = "auto",
        require_tier: str = "free",
        human_delay: bool = True,
    ) -> Dict[str, Any]:
        """JIT pattern: route inference with human-like delays.

        Selects a backend without spawning a persistent session. Adds
        configurable random delay to simulate human pacing, and mixes
        T4/A100 hardware naturally by selecting different accounts.

        Args:
            prompt: Text prompt.
            model: Model identifier or ``"auto"``.
            require_tier: Minimum account tier — ``"free"`` or ``"pro"``.
            human_delay: Override the global human_delays setting for this call.

        Returns:
            Dict with ``response``, ``backend``, ``model``, ``account``,
            ``latency_ms``, and ``jit`` flag.

        Raises:
            ComputeUnavailableError: If no backend is available.
        """
        if self._active_jit_sessions >= MAX_JIT_SESSIONS:
            raise ComputeUnavailableError(
                f"Max concurrent JIT sessions ({MAX_JIT_SESSIONS}) reached"
            )

        if human_delay and self._jit_config.get("human_delays", True):
            self._jit_human_delay()

        self._active_jit_sessions += 1
        try:
            # Vary GPU tier naturally — occasionally pick pro if available
            effective_tier = require_tier
            if require_tier == "free" and random.random() < 0.25:
                # Try pro opportunistically 25% of the time
                probe = self.get_best_account_for_tier("pro")
                if probe is not None:
                    effective_tier = "pro"

            result = self.route_inference(
                prompt=prompt,
                model_preference=model,
                require_tier=effective_tier,
                fallback_to_local=True,
            )
            result["jit"] = True
            result["tier_used"] = effective_tier
            return result
        finally:
            self._active_jit_sessions -= 1

    def jit_execute(
        self,
        code: str,
        timeout: int = 60,
    ) -> Dict[str, Any]:
        """JIT code execution: route to the best available Colab session.

        Finds a healthy tunnel session, sends the code, and returns results.
        Falls back to Colab AI agent if no tunnel is available.

        Args:
            code: Python source code to execute.
            timeout: Execution timeout in seconds.

        Returns:
            Dict with ``stdout``, ``stderr``, ``returncode``, ``backend``,
            ``account``, ``latency_ms``.

        Raises:
            ComputeUnavailableError: If no execution backend is reachable.
        """
        if self._active_jit_sessions >= MAX_JIT_SESSIONS:
            raise ComputeUnavailableError(
                f"Max concurrent JIT sessions ({MAX_JIT_SESSIONS}) reached"
            )

        self._jit_human_delay()
        start = time.time()
        self._active_jit_sessions += 1
        try:
            # Try tunnel first
            from engine.integrations.colab_tunnel_server import get_tunnel_server
            server = get_tunnel_server()
            healthy = [s for s in server._sessions.values() if s.healthy]
            if healthy:
                session = random.choice(healthy)
                try:
                    resp = requests.post(
                        f"{session.tunnel_url}/execute",
                        json={"code": code, "timeout": timeout},
                        timeout=timeout + 5,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        data["backend"] = "tunnel"
                        data["account"] = session.account_name
                        data["latency_ms"] = int((time.time() - start) * 1000)
                        data["jit"] = True
                        return data
                except Exception as exc:
                    logger.debug("JIT tunnel execute failed: %s", exc)

            # Fall back to Colab client run_python
            account = self.get_best_account_for_tier("free")
            if account is not None:
                from engine.integrations.colab_client import get_colab_client
                client = get_colab_client(account.name)
                if client is not None:
                    result = client.run_python(code, timeout=timeout)
                    result["backend"] = "colab_agent"
                    result["account"] = account.name
                    result["latency_ms"] = int((time.time() - start) * 1000)
                    result["jit"] = True
                    return result
        except Exception as exc:
            logger.debug("jit_execute error: %s", exc)
        finally:
            self._active_jit_sessions -= 1

        raise ComputeUnavailableError(
            "No JIT execution backend available (tunnel, colab_agent both failed)"
        )

    # ──── Tier detection ──────────────────────────────────────────────────────

    def detect_tier(self, account: GoogleAccount) -> AccountTier:
        """Detect account tier by querying Colab hardware availability.

        Args:
            account: GoogleAccount to inspect.

        Returns:
            AccountTier with tier, hardware, models, and limits populated.
        """
        hardware_list: List[str] = []
        tier = "free"

        try:
            from engine.integrations.colab_client import get_colab_client
            client = get_colab_client(account.name)
            if client is None:
                raise RuntimeError("No client for account")
            user_info = client.get_user_info()

            for v in (user_info.get("pro_tiers") or {}).values():
                if isinstance(v, list):
                    hardware_list.extend(v)
            for v in (user_info.get("free_tiers") or {}).values():
                if isinstance(v, list):
                    hardware_list.extend(v)

            if any(hw in TIER_PRO_HARDWARE for hw in hardware_list):
                tier = "pro"
        except Exception as exc:
            logger.debug("Could not detect tier for %s: %s", account.name, exc)
            hardware_list = TIER_FREE_HARDWARE.copy()

        models = MODELS_PRO if tier == "pro" else MODELS_FREE
        limits = LIMITS_PRO.copy() if tier == "pro" else LIMITS_FREE.copy()

        account_tier = AccountTier(
            account_name=account.name,
            tier=tier,
            hardware=hardware_list,
            available_models=models,
            limits=limits,
            usage={k: 0.0 for k in limits},
        )
        self._tiers[account.name] = account_tier
        return account_tier

    def get_available_models(self, tier: str = "free") -> List[str]:
        """Return model list for the given tier.

        Args:
            tier: "free" or "pro".

        Returns:
            List of model identifier strings.
        """
        return MODELS_PRO if tier == "pro" else MODELS_FREE

    # ──── Account selection ───────────────────────────────────────────────────

    def get_best_account_for_tier(
        self, required_tier: str = "free"
    ) -> Optional[GoogleAccount]:
        """Find the best available account at the required tier.

        Skips accounts that have exceeded their daily limits.

        Args:
            required_tier: Minimum tier — "free" accepts any, "pro" requires pro.

        Returns:
            A GoogleAccount, or None if none qualify.
        """
        try:
            from engine.integrations.google_account_pool import get_account_pool
            pool = get_account_pool()

            for acct_info in pool.list_accounts():
                if "colab" not in acct_info.get("services", []):
                    continue
                name = acct_info["name"]
                account = pool.get_by_name(name)
                if account is None:
                    continue

                # Check tier requirement
                tier_info = self._tiers.get(name)
                acct_tier = tier_info.tier if tier_info else "free"
                if required_tier == "pro" and acct_tier != "pro":
                    continue

                # Check limits
                base_limits = tier_info.limits if tier_info else LIMITS_FREE.copy()
                usage = self._usage.get(name, {})
                over_limit = False
                for service, base_limit in base_limits.items():
                    custom = self._custom_limits.get(name, {}).get(service)
                    effective_limit = custom if custom is not None else base_limit
                    used = usage.get(service, 0.0)
                    if used >= effective_limit:
                        over_limit = True
                        break

                if not over_limit:
                    return account

        except Exception as exc:
            logger.debug("get_best_account_for_tier error: %s", exc)

        return None

    # ──── Usage tracking ──────────────────────────────────────────────────────

    def track_usage(
        self, account_name: str, service: str, units: float = 1.0
    ) -> None:
        """Increment a usage counter for an account/service pair.

        Args:
            account_name: Account to track usage for.
            service: Service key (e.g. "colab_requests_per_day").
            units: Amount to increment by.
        """
        if account_name not in self._usage:
            self._usage[account_name] = {}
        self._usage[account_name][service] = (
            self._usage[account_name].get(service, 0.0) + units
        )

    def check_limit(self, account_name: str, service: str) -> Tuple[float, float]:
        """Return current usage and effective limit for a service.

        Args:
            account_name: Account to check.
            service: Service key.

        Returns:
            Tuple of (used, limit). Limit is float('inf') if unlimited.
        """
        tier_info = self._tiers.get(account_name)
        base_limit = LIMITS_FREE.get(service, float("inf"))
        if tier_info:
            base_limit = tier_info.limits.get(service, float("inf"))

        custom = self._custom_limits.get(account_name, {}).get(service)
        effective_limit = custom if custom is not None else base_limit

        used = self._usage.get(account_name, {}).get(service, 0.0)
        return used, effective_limit

    def reset_daily_usage(self) -> None:
        """Reset all usage counters to 0.0."""
        for account_name in self._usage:
            self._usage[account_name] = {
                k: 0.0 for k in self._usage[account_name]
            }

    # ──── Inference routing ───────────────────────────────────────────────────

    def route_inference(
        self,
        prompt: str,
        model_preference: str = "auto",
        require_tier: Optional[str] = None,
        fallback_to_local: bool = True,
    ) -> Dict[str, Any]:
        """Route an inference request to the best available backend.

        Priority: tunnel → colab_agent → lmstudio.

        Args:
            prompt: Text prompt.
            model_preference: Model identifier or "auto".
            require_tier: Minimum account tier ("free", "pro", or None).
            fallback_to_local: Whether to try LMStudio if no cloud backend.

        Returns:
            Dict with response, backend, model, account, latency_ms.

        Raises:
            ComputeUnavailableError: If no backend is available.
        """
        start = time.time()
        model = model_preference if model_preference != "auto" else "gemini-2.5-flash-exp"

        # 1. Try active tunnel sessions
        try:
            from engine.integrations.colab_tunnel_server import get_tunnel_server
            server = get_tunnel_server()
            healthy_sessions = [s for s in server._sessions.values() if s.healthy]
            for session in healthy_sessions:
                try:
                    resp = requests.post(
                        f"{session.tunnel_url}/infer",
                        json={"prompt": prompt, "model": model},
                        timeout=30,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        self.track_usage(session.account_name, "colab_requests_per_day")
                        return {
                            "response": data.get("response", ""),
                            "backend": "tunnel",
                            "model": data.get("model", model),
                            "account": session.account_name,
                            "latency_ms": int((time.time() - start) * 1000),
                        }
                except Exception as exc:
                    logger.debug("Tunnel %s inference failed: %s", session.tunnel_url, exc)
        except Exception as exc:
            logger.debug("Could not access tunnel server: %s", exc)

        # 2. Try Colab AI agent
        try:
            from engine.integrations.colab_client import get_colab_client
            account = self.get_best_account_for_tier(require_tier or "free")
            if account is not None:
                client = get_colab_client(account.name)
                if client is not None:
                    response = client.ask(prompt)
                    self.track_usage(account.name, "colab_requests_per_day")
                    return {
                        "response": response,
                        "backend": "colab_agent",
                        "model": "gemini-2.5-flash-exp",
                        "account": account.name,
                        "latency_ms": int((time.time() - start) * 1000),
                    }
        except Exception as exc:
            logger.debug("Colab agent inference failed: %s", exc)

        # 3. Try LMStudio
        if fallback_to_local:
            try:
                models_resp = requests.get(
                    "http://localhost:1234/api/v1/models", timeout=2
                )
                if models_resp.status_code == 200:
                    models_data = models_resp.json()
                    model_id = model_preference
                    if model_preference == "auto":
                        model_list = models_data.get("data", [])
                        model_id = model_list[0]["id"] if model_list else "default"

                    lms_resp = requests.post(
                        "http://localhost:1234/api/v1/chat/completions",
                        json={
                            "model": model_id,
                            "messages": [{"role": "user", "content": prompt}],
                        },
                        timeout=60,
                    )
                    if lms_resp.status_code == 200:
                        lms_data = lms_resp.json()
                        response_text = lms_data["choices"][0]["message"]["content"]
                        return {
                            "response": response_text,
                            "backend": "lmstudio",
                            "model": model_id,
                            "account": "local",
                            "latency_ms": int((time.time() - start) * 1000),
                        }
            except Exception as exc:
                logger.debug("LMStudio inference failed: %s", exc)

        raise ComputeUnavailableError(
            "No compute backend available (tunnel, colab_agent, lmstudio all failed or unavailable)"
        )

    def route_embedding(self, texts: List[str]) -> Dict[str, Any]:
        """Route embedding requests, preferring tunnel then local sentence-transformers.

        Args:
            texts: List of strings to embed.

        Returns:
            Dict with embeddings, backend, model.

        Raises:
            ComputeUnavailableError: If no embedding backend is available.
        """
        # Try tunnel
        try:
            from engine.integrations.colab_tunnel_server import get_tunnel_server
            server = get_tunnel_server()
            healthy_sessions = [s for s in server._sessions.values() if s.healthy]
            for session in healthy_sessions:
                try:
                    resp = requests.post(
                        f"{session.tunnel_url}/embed",
                        json={"texts": texts},
                        timeout=30,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        return {
                            "embeddings": data.get("embeddings", []),
                            "backend": "tunnel",
                            "model": data.get("model", "text-embedding-004"),
                        }
                except Exception as exc:
                    logger.debug("Tunnel embedding failed: %s", exc)
        except Exception as exc:
            logger.debug("Could not access tunnel for embeddings: %s", exc)

        # Try local sentence-transformers
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
            model = SentenceTransformer("all-MiniLM-L6-v2")
            embeddings = model.encode(texts).tolist()
            return {
                "embeddings": embeddings,
                "backend": "sentence_transformers",
                "model": "all-MiniLM-L6-v2",
            }
        except Exception as exc:
            logger.debug("sentence-transformers not available: %s", exc)

        raise ComputeUnavailableError("No embedding backend available")

    # ──── Status ──────────────────────────────────────────────────────────────

    def get_status(self) -> Dict[str, Any]:
        """Return a snapshot of all compute backends and usage.

        Returns:
            Dict with accounts, tunnels, and lmstudio info.
        """
        accounts_info: List[Dict[str, Any]] = []
        try:
            from engine.integrations.google_account_pool import get_account_pool
            pool = get_account_pool()
            for acct_info in pool.list_accounts():
                name = acct_info["name"]
                tier_info = self._tiers.get(name)
                accounts_info.append({
                    "name": name,
                    "tier": tier_info.tier if tier_info else "unknown",
                    "usage": self._usage.get(name, {}),
                    "limits": tier_info.limits if tier_info else {},
                    "features": self._feature_config.get(name, {}),
                })
        except Exception as exc:
            logger.debug("Could not get account info: %s", exc)

        tunnels: List[Dict[str, Any]] = []
        try:
            from engine.integrations.colab_tunnel_server import get_tunnel_server
            server = get_tunnel_server()
            for s in server._sessions.values():
                tunnels.append({
                    "account_name": s.account_name,
                    "tunnel_url": s.tunnel_url,
                    "hardware": s.hardware,
                    "healthy": s.healthy,
                    "started_at": s.started_at,
                    "tunnel_type": s.tunnel_type,
                })
        except Exception as exc:
            logger.debug("Could not get tunnel info: %s", exc)

        lmstudio: Dict[str, Any] = {"available": False, "models": []}
        try:
            resp = requests.get("http://localhost:1234/api/v1/models", timeout=2)
            if resp.status_code == 200:
                data = resp.json()
                lmstudio = {
                    "available": True,
                    "models": [m["id"] for m in data.get("data", [])],
                }
        except Exception:
            pass

        return {"accounts": accounts_info, "tunnels": tunnels, "lmstudio": lmstudio}

    # ──── Feature / limit config ──────────────────────────────────────────────

    def set_feature_config(
        self, account_name: str, unlocked_features: List[str]
    ) -> None:
        """Store the list of unlocked features for an account.

        Args:
            account_name: Account to configure.
            unlocked_features: List of feature strings to unlock.
        """
        if account_name not in self._feature_config:
            self._feature_config[account_name] = {}
        self._feature_config[account_name]["unlocked_features"] = list(unlocked_features)

    def is_feature_unlocked(self, account_name: str, feature: str) -> bool:
        """Check if a feature is unlocked for an account.

        Args:
            account_name: Account to check.
            feature: Feature name.

        Returns:
            True if the feature is in the unlocked list.
        """
        return feature in self._feature_config.get(account_name, {}).get(
            "unlocked_features", []
        )

    def configure_limits(
        self, account_name: str, service: str, limit: float
    ) -> None:
        """Override the default limit for a service on an account.

        Args:
            account_name: Account to configure.
            service: Service key to set limit for.
            limit: New limit value. Use float('inf') for unlimited.
        """
        if account_name not in self._custom_limits:
            self._custom_limits[account_name] = {}
        self._custom_limits[account_name][service] = limit
        logger.debug(
            "Configured %s.%s = %s", account_name, service,
            "unlimited" if limit == float("inf") else limit,
        )


# ──── Singleton ───────────────────────────────────────────────────────────────

_router_instance: Optional[ComputeRouter] = None


def get_compute_router() -> ComputeRouter:
    """Get or create the singleton ComputeRouter.

    Returns:
        Singleton ComputeRouter instance.
    """
    global _router_instance
    if _router_instance is None:
        _router_instance = ComputeRouter()
    return _router_instance
