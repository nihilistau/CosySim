"""Interceptor: PolicyEnforcerInterceptor.

Split from engine/agents/interceptors.py by scripts/hindsight/split_interceptors.py.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from engine.mcp.comms_framework import (
    InterceptorBase,
    ResponseContext,
    TRIGGER_OPTIONAL,
    TRIGGER_REQUIRED,
)

logger = logging.getLogger(__name__)

class PolicyEnforcerInterceptor(InterceptorBase):
    """
    Pre-call: inject token-budget instruction so the model knows the expected
    reply length.
    """
    name     = "policy_enforcer"
    priority = 60

    def pre_call(self, ctx: ResponseContext) -> None:
        policy: Any = ctx.get("policy")
        if policy is None:
            return
        ctx["system_prompt"] = ctx.get("system_prompt", "") + (
            f"\n\nKeep your reply between {policy.min_reply_tokens} and "
            f"{policy.max_reply_tokens} tokens."
        )
