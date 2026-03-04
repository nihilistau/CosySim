"""AI Studio MakerSuiteService client — reverse-engineered gRPC-web API.

Derived from HAR + V8 heap analysis (March 2026). 136 methods extracted.
See docs/AISTUDIO_API_REFERENCE.md for full protocol spec.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)

GRPC_BASE = "https://alkalimakersuite-pa.clients6.google.com/$rpc/google.internal.alkali.applications.makersuite.v1.MakerSuiteService"
STREAMING_BASE = "https://webchannel-alkalimakersuite-pa.clients6.google.com"

# Confirmed API keys (rotate via GenerateCloudApiKey)
API_KEYS = [
    "REDACTED-GOOGLE-API-KEY",
    "REDACTED-GOOGLE-API-KEY",
    "REDACTED-GOOGLE-API-KEY",
]


def _build_sapisidhash(sapisid: str, origin: str = "https://aistudio.google.com") -> str:
    """Build SAPISIDHASH auth header value.

    Args:
        sapisid: SAPISID cookie value.
        origin: Origin URL.

    Returns:
        Full Authorization header value string.
    """
    ts = int(time.time())
    digest = hashlib.sha1(f"{ts} {sapisid} {origin}".encode()).hexdigest()
    return f"SAPISIDHASH {ts}_{digest}"


class AIStudioClient:
    """Programmatic AI Studio access via reverse-engineered MakerSuiteService gRPC-web API.

    Covers 136 methods including: GenerateContent, ProxyUnaryCall, ListModels,
    GenerateAccessToken, CreateApplet, ProvisionAndInitializeApplet, and more.

    Args:
        cookies: Dict of Google session cookies.
        api_key: AI Studio API key (defaults to first in list).
    """

    def __init__(self, cookies: dict[str, str], api_key: str = API_KEYS[0]) -> None:
        self._cookies = cookies
        self._api_key = api_key
        self._session = requests.Session()
        self._session.cookies.update(cookies)

    # ──── Internal ────

    def _headers(self) -> dict[str, str]:
        sapisid = self._cookies.get("SAPISID", "")
        return {
            "Authorization": _build_sapisidhash(sapisid),
            "X-Goog-Api-Key": self._api_key,
            "X-Goog-Authuser": "0",
            "Content-Type": "application/json",
            "Origin": "https://aistudio.google.com",
            "Referer": "https://aistudio.google.com/",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
        }

    def _post(self, method: str, body: dict) -> dict:
        """Call a MakerSuiteService method.

        Args:
            method: Method name (e.g. 'ListModels').
            body: Request body dict.

        Returns:
            Response JSON dict.

        Raises:
            requests.HTTPError: On non-2xx response.
        """
        url = f"{GRPC_BASE}/{method}"
        resp = self._session.post(url, json=body, headers=self._headers(), timeout=60)
        resp.raise_for_status()
        try:
            return resp.json()
        except Exception:
            return {"raw": resp.text}

    def _post_safe(self, method: str, body: dict) -> dict:
        """Call method with error handling (returns empty dict on failure)."""
        try:
            return self._post(method, body)
        except Exception as exc:
            logger.error("AIStudio %s failed: %s", method, exc)
            return {}

    # ──── Auth ────

    def generate_access_token(self) -> Optional[str]:
        """Get a fresh OAuth2 bearer token (ya29.xxx).

        Returns:
            Access token string, or None on failure.
        """
        resp = self._post_safe("GenerateAccessToken", {})
        return resp.get("accessToken")

    def check_user_status(self) -> dict:
        """Return user account status and feature flags.

        Returns:
            Dict with status flags.
        """
        return self._post_safe("CheckUserStatus", {})

    def get_user_preferences(self) -> dict:
        """Return user preferences.

        Returns:
            Preferences dict.
        """
        return self._post_safe("GetUserPreferences", {})

    def update_user_preferences(self, prefs: dict) -> dict:
        """Update user preferences.

        Args:
            prefs: Preferences dict to update.

        Returns:
            Updated preferences dict.
        """
        return self._post_safe("UpdateUserPreferences", prefs)

    def get_user_restrictions(self) -> dict:
        """Return user restrictions (SafeSearch, content policy, etc.).

        Returns:
            Restrictions dict.
        """
        return self._post_safe("GetUserRestrictions", {})

    # ──── Models ────

    def list_models(self) -> list[dict]:
        """Return all available Gemini models.

        Returns:
            List of model dicts with name, displayName, inputTokenLimit, etc.
        """
        resp = self._post_safe("ListModels", {})
        return resp.get("models", [])

    def get_model(self, model_name: str) -> dict:
        """Return details for a specific model.

        Args:
            model_name: Model name (e.g. 'models/gemini-3-flash-preview').

        Returns:
            Model details dict.
        """
        return self._post_safe("GetModel", {"model": model_name})

    def get_model_quota(self, model_name: str) -> dict:
        """Return quota info for a model.

        Args:
            model_name: Model name.

        Returns:
            Quota dict.
        """
        return self._post_safe("GetModelQuota", {"model": model_name})

    # ──── Generation ────

    def generate_content(
        self,
        model: str,
        prompt: str,
        system_instruction: str = "",
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> dict:
        """Generate content using the specified model.

        Args:
            model: Model name (e.g. 'models/gemini-3-flash-preview').
            prompt: User prompt text.
            system_instruction: Optional system instruction.
            temperature: Generation temperature (0.0-2.0).
            max_tokens: Maximum output tokens.

        Returns:
            GenerateContent response dict with candidates and usageMetadata.
        """
        body: dict[str, Any] = {
            "model": model,
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if system_instruction:
            body["systemInstruction"] = {"parts": [{"text": system_instruction}]}
        return self._post_safe("GenerateContent", body)

    def proxy_generate(
        self,
        model: str,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> dict:
        """Generate via ProxyUnaryCall — returns thoughtSignature for thinking tokens.

        Args:
            model: Model name.
            prompt: User prompt.
            temperature: Temperature.
            max_tokens: Max output tokens.

        Returns:
            Full Gemini response including thoughtSignature if available.
        """
        body: dict[str, Any] = {
            "model": model,
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        return self._post_safe("ProxyUnaryCall", body)

    def count_tokens(self, model: str, prompt: str) -> int:
        """Count tokens for a prompt without generating.

        Args:
            model: Model name.
            prompt: Prompt text.

        Returns:
            Token count integer.
        """
        resp = self._post_safe("CountTokens", {
            "model": model,
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        })
        return resp.get("totalTokens", 0)

    def enhance_prompt(self, prompt: str, model: str = "models/gemini-3-flash-preview") -> str:
        """AI-improve a prompt via EnhancePrompt.

        Args:
            prompt: Original prompt to enhance.
            model: Model to use for enhancement.

        Returns:
            Enhanced prompt string.
        """
        resp = self._post_safe("EnhancePrompt", {"prompt": prompt, "model": model})
        return resp.get("enhancedPrompt", prompt)

    def generate_image(self, prompt: str, model: str = "models/imagen-4.0-generate-001") -> dict:
        """Generate an image.

        Args:
            prompt: Image generation prompt.
            model: Imagen model name.

        Returns:
            Response with image data.
        """
        return self._post_safe("GenerateImage", {"prompt": prompt, "model": model})

    def generate_video(self, prompt: str, model: str = "models/veo-3.1-generate-preview") -> dict:
        """Start a video generation job.

        Args:
            prompt: Video generation prompt.
            model: Veo model name.

        Returns:
            Operation dict with operationId for polling.
        """
        return self._post_safe("GenerateVideo", {"prompt": prompt, "model": model})

    def get_video_operation(self, operation_id: str) -> dict:
        """Check status of a video generation operation.

        Args:
            operation_id: Operation ID from GenerateVideo.

        Returns:
            Operation status dict (done, videoUri if complete).
        """
        return self._post_safe("GetGenerateVideoOperation", {"operationId": operation_id})

    # ──── Prompts ────

    def list_prompts(self, page_size: int = 50) -> list[dict]:
        """List saved prompts.

        Returns:
            List of prompt dicts.
        """
        resp = self._post_safe("ListPrompts", {"pageSize": page_size})
        return resp.get("prompts", [])

    def create_prompt(self, display_name: str, text: str, model: str = "") -> dict:
        """Create a new prompt template.

        Args:
            display_name: Prompt name.
            text: Prompt text.
            model: Default model for this prompt.

        Returns:
            Created prompt dict with ID.
        """
        return self._post_safe("CreatePrompt", {
            "displayName": display_name,
            "text": text,
            "model": model,
        })

    # ──── Applets (AI Studio Apps) ────

    def list_applets(self, page_size: int = 50) -> list[dict]:
        """List user's AI Studio apps.

        Returns:
            List of applet dicts with id, displayName, deploymentUrl.
        """
        resp = self._post_safe("ListApplets", {"pageSize": page_size})
        return resp.get("applets", [])

    def get_applet(self, applet_id: str) -> dict:
        """Get an AI Studio app by UUID.

        Args:
            applet_id: App UUID.

        Returns:
            Full applet config dict.
        """
        return self._post_safe("GetApplet", {"appletId": applet_id})

    def create_applet(self, display_name: str, system_instruction: str, model: str) -> dict:
        """Create a new AI Studio app.

        Args:
            display_name: App name.
            system_instruction: System prompt.
            model: Default model.

        Returns:
            Created applet dict with ID.
        """
        return self._post_safe("CreateApplet", {
            "displayName": display_name,
            "systemInstruction": system_instruction,
            "model": model,
        })

    def deploy_applet(self, applet_id: str) -> dict:
        """Deploy an AI Studio app to Cloud Run.

        Args:
            applet_id: App UUID.

        Returns:
            Dict with deploymentUrl and serviceId.
        """
        return self._post_safe("ProvisionAndInitializeApplet", {"appletId": applet_id})

    def get_applet_logs(self, applet_id: str) -> list[str]:
        """Get Cloud Run service logs for an app.

        Args:
            applet_id: App UUID.

        Returns:
            List of log line strings.
        """
        resp = self._post_safe("GetAppletCloudRunServiceLogs", {"appletId": applet_id})
        return resp.get("logLines", [])

    def list_applet_secrets(self, applet_id: str) -> list[dict]:
        """List environment variables/secrets for an app.

        Args:
            applet_id: App UUID.

        Returns:
            List of secret dicts with key and value.
        """
        resp = self._post_safe("ListAppletSecrets", {"appletId": applet_id})
        return resp.get("secrets", [])

    def upsert_applet_secret(self, applet_id: str, key: str, value: str) -> dict:
        """Create or update an app secret/env var.

        Args:
            applet_id: App UUID.
            key: Secret key.
            value: Secret value.

        Returns:
            Updated secret dict.
        """
        return self._post_safe("UpsertAppletSecret", {
            "appletId": applet_id,
            "key": key,
            "value": value,
        })

    # ──── Cloud Infrastructure ────

    def list_cloud_projects(self) -> list[dict]:
        """List linked GCP projects.

        Returns:
            List of project dicts.
        """
        resp = self._post_safe("ListCloudProjects", {})
        return resp.get("projects", [])

    def list_cloud_api_keys(self, project_id: str = "") -> list[dict]:
        """List API keys for a GCP project.

        Args:
            project_id: GCP project ID.

        Returns:
            List of API key dicts.
        """
        resp = self._post_safe("ListCloudApiKeys", {"projectId": project_id})
        return resp.get("apiKeys", [])

    def generate_cloud_api_key(self, project_id: str, display_name: str = "CosySim") -> dict:
        """Generate a new AI Studio API key.

        Args:
            project_id: GCP project ID.
            display_name: Key display name.

        Returns:
            Dict with keyString (the actual key).
        """
        return self._post_safe("GenerateCloudApiKey", {
            "projectId": project_id,
            "displayName": display_name,
        })

    # ──── Datasets (Fine-tuning) ────

    def list_datasets(self) -> list[dict]:
        """List fine-tuning datasets.

        Returns:
            List of dataset dicts.
        """
        resp = self._post_safe("ListDatasets", {})
        return resp.get("datasets", [])

    def create_dataset(self, display_name: str) -> dict:
        """Create a new fine-tuning dataset.

        Args:
            display_name: Dataset name.

        Returns:
            Created dataset dict with ID.
        """
        return self._post_safe("CreateDataset", {"displayName": display_name})

    def create_interaction(self, dataset_id: str, prompt: str, response: str) -> dict:
        """Add a training example to a dataset.

        Args:
            dataset_id: Target dataset ID.
            prompt: Input prompt.
            response: Expected output.

        Returns:
            Created interaction dict.
        """
        return self._post_safe("CreateInteraction", {
            "datasetId": dataset_id,
            "input": {"text": prompt},
            "output": {"text": response},
        })

    # ──── Logging ────

    def get_logging_context(self) -> dict:
        """Return logging context and configuration.

        Returns:
            Logging context dict.
        """
        return self._post_safe("GetLoggingContext", {})


# ──── Singleton ────

_client: Optional[AIStudioClient] = None


def get_aistudio_client(cookies: Optional[dict] = None, api_key: str = API_KEYS[0]) -> AIStudioClient:
    """Get or create the singleton AI Studio client.

    Args:
        cookies: Override cookies (uses pool if not provided).
        api_key: API key override.

    Returns:
        AIStudioClient instance.
    """
    global _client
    if _client is None or cookies:
        if cookies is None:
            try:
                from engine.integrations.google_account_pool import get_account_pool
                pool = get_account_pool()
                account = pool.get_best_account(["aistudio", "gemini"])
                cookies = account.cookies if account else {}
            except Exception:
                cookies = {}
        _client = AIStudioClient(cookies, api_key=api_key)
    return _client
