"""AI Studio MakerSuiteService client — reverse-engineered gRPC-web API.

Derived from HAR + V8 heap analysis (March 2026). 136 methods extracted.
See docs/AISTUDIO_API_REFERENCE.md for full protocol spec.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import requests

logger = logging.getLogger(__name__)

GRPC_BASE = "https://alkalimakersuite-pa.clients6.google.com/$rpc/google.internal.alkali.applications.makersuite.v1.MakerSuiteService"
STREAMING_BASE = "https://webchannel-alkalimakersuite-pa.clients6.google.com"
_REST_BASE = "https://generativelanguage.googleapis.com/v1beta"

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

    def _rest_request(
        self,
        method: str,
        path: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Call the Gemini REST API (v1beta).

        Args:
            method: HTTP method (GET, POST, DELETE).
            path: API path relative to v1beta base (e.g. 'files' or 'models/x:embedContent').
            data: JSON body dict for POST requests.
            params: Query parameter dict.

        Returns:
            Response JSON dict.

        Raises:
            requests.HTTPError: On non-2xx response.
        """
        url = f"{_REST_BASE}/{path}"
        all_params: Dict[str, Any] = {"key": self._api_key}
        if params:
            all_params.update(params)
        resp = self._session.request(
            method,
            url,
            json=data,
            params=all_params,
            headers={"Content-Type": "application/json"},
            timeout=60,
        )
        resp.raise_for_status()
        try:
            return resp.json()
        except Exception:
            return {"raw": resp.text}

    # ──── Streaming ────

    def stream_generate_content(
        self,
        model: str,
        contents: List[Dict[str, Any]],
        system_instruction: Optional[str] = None,
        generation_config: Optional[Dict[str, Any]] = None,
    ) -> Iterator[str]:
        """Stream generated content token by token (streamGenerateContent).

        Args:
            model: Model name, e.g. ``"gemini-2.5-flash"``.
            contents: List of content turn dicts with ``role`` and ``parts``.
            system_instruction: Optional system prompt text.
            generation_config: Optional generation parameters.

        Yields:
            Incremental text chunks as they arrive.
        """
        body: Dict[str, Any] = {"contents": contents}
        if system_instruction:
            body["systemInstruction"] = {"parts": [{"text": system_instruction}]}
        if generation_config:
            body["generationConfig"] = generation_config

        endpoint = (
            f"{_REST_BASE}/models/{model}:streamGenerateContent"
            f"?alt=sse&key={self._api_key}"
        )
        headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}

        with self._session.post(
            endpoint, json=body, headers=headers, stream=True, timeout=120
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    for candidate in chunk.get("candidates", []):
                        for part in candidate.get("content", {}).get("parts", []):
                            if text := part.get("text"):
                                yield text
                except (json.JSONDecodeError, KeyError):
                    continue

    # ──── Embeddings ────

    def embed_content(
        self,
        model: str,
        content: str,
        task_type: str = "RETRIEVAL_DOCUMENT",
        title: Optional[str] = None,
    ) -> List[float]:
        """Generate an embedding vector for a piece of text (embedContent).

        Args:
            model: Embedding model, e.g. ``"text-embedding-004"``.
            content: Text to embed.
            task_type: Embedding task type. One of: RETRIEVAL_QUERY,
                RETRIEVAL_DOCUMENT, SEMANTIC_SIMILARITY, CLASSIFICATION,
                CLUSTERING, QUESTION_ANSWERING, FACT_VERIFICATION.
            title: Optional title for RETRIEVAL_DOCUMENT tasks.

        Returns:
            List of float embedding values.
        """
        body: Dict[str, Any] = {
            "model": f"models/{model}",
            "content": {"parts": [{"text": content}]},
            "taskType": task_type,
        }
        if title:
            body["title"] = title
        result = self._rest_request("POST", f"models/{model}:embedContent", data=body)
        embedding = result.get("embedding", {})
        return embedding.get("values", [])

    # ──── File management ────

    def list_files(
        self,
        page_size: int = 100,
        page_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List all uploaded files in the AI Studio account (ListFiles).

        Args:
            page_size: Maximum number of files to return.
            page_token: Pagination token from a previous call.

        Returns:
            Dict with ``files`` list and optional ``nextPageToken``.
        """
        params: Dict[str, Any] = {"pageSize": page_size}
        if page_token:
            params["pageToken"] = page_token
        return self._rest_request("GET", "files", params=params)

    def create_file(
        self,
        file_path: str,
        display_name: Optional[str] = None,
        mime_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Upload a file to AI Studio for multimodal inference (CreateFile).

        Supported types: images, audio, video, PDF, text.
        Uploaded files expire after 48 hours.

        Args:
            file_path: Local path to the file.
            display_name: Human-readable name. Defaults to filename.
            mime_type: MIME type override. Auto-detected if omitted.

        Returns:
            File metadata dict with ``name``, ``uri``, ``state``, ``mimeType``.
        """
        import mimetypes as _mimetypes
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        if not mime_type:
            mime_type, _ = _mimetypes.guess_type(str(path))
            mime_type = mime_type or "application/octet-stream"
        if not display_name:
            display_name = path.name

        # Phase 1: initiate resumable upload
        metadata = {"file": {"displayName": display_name, "mimeType": mime_type}}
        init_url = (
            f"https://generativelanguage.googleapis.com/upload/v1beta/files"
            f"?uploadType=resumable&key={self._api_key}"
        )
        init_headers = {
            "X-Goog-Upload-Protocol": "resumable",
            "X-Goog-Upload-Command": "start",
            "X-Goog-Upload-Header-Content-Length": str(path.stat().st_size),
            "X-Goog-Upload-Header-Content-Type": mime_type,
            "Content-Type": "application/json",
        }
        init_resp = self._session.post(
            init_url, json=metadata, headers=init_headers, timeout=30
        )
        init_resp.raise_for_status()
        upload_url = init_resp.headers.get("X-Goog-Upload-URL")
        if not upload_url:
            raise RuntimeError("No upload URL returned from AI Studio")

        # Phase 2: upload file data
        file_data = path.read_bytes()
        upload_headers = {
            "Content-Type": mime_type,
            "X-Goog-Upload-Offset": "0",
            "X-Goog-Upload-Command": "upload, finalize",
        }
        upload_resp = self._session.post(
            upload_url, data=file_data, headers=upload_headers, timeout=300
        )
        upload_resp.raise_for_status()
        result = upload_resp.json()
        return result.get("file", result)

    def get_file(self, file_name: str) -> Dict[str, Any]:
        """Get metadata for an uploaded file (GetFile).

        Args:
            file_name: File name in format ``files/{id}`` or just the ID.

        Returns:
            File metadata dict.
        """
        if not file_name.startswith("files/"):
            file_name = f"files/{file_name}"
        return self._rest_request("GET", file_name)

    def delete_file(self, file_name: str) -> None:
        """Delete an uploaded file (DeleteFile).

        Args:
            file_name: File name in format ``files/{id}`` or just the ID.
        """
        if not file_name.startswith("files/"):
            file_name = f"files/{file_name}"
        self._rest_request("DELETE", file_name)
        logger.debug("Deleted file %s", file_name)

    # ──── Text-to-speech ────

    def text_to_speech(
        self,
        text: str,
        voice: str = "Kore",
        model: str = "gemini-2.5-flash-preview-tts",
        output_path: Optional[str] = None,
    ) -> bytes:
        """Convert text to speech using Gemini TTS.

        Args:
            text: Text to synthesize.
            voice: Voice name. Options include: Aoede, Charon, Fenrir, Kore,
                Orus, Puck, Leda, Zephyr, etc.
            model: TTS model name.
            output_path: Optional path to save the audio file to.

        Returns:
            Raw audio bytes. If output_path is given, also saves to file.
        """
        body: Dict[str, Any] = {
            "contents": [{"parts": [{"text": text}], "role": "user"}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}
                },
            },
        }
        result = self._rest_request("POST", f"models/{model}:generateContent", data=body)

        audio_data = b""
        for candidate in result.get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                if inline_data := part.get("inlineData", {}):
                    import base64
                    audio_data = base64.b64decode(inline_data.get("data", ""))
                    break

        if output_path and audio_data:
            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(audio_data)
            logger.info("TTS saved to %s (%d bytes)", output_path, len(audio_data))

        return audio_data

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
