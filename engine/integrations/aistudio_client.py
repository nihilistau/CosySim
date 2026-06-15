"""AI Studio MakerSuiteService client — reverse-engineered gRPC-web API.

Derived from HAR + V8 heap analysis (March 2026). 136 methods extracted.
See docs/AISTUDIO_API_REFERENCE.md for full protocol spec.

Version: v1.57.0 [2026-03-26]

Change Log:
    v1.57.0 [2026-03-26] — Add generate_structured() for Gemini JSON schema output
                            via google.genai SDK; module-level convenience function
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import requests

logger = logging.getLogger(__name__)

GRPC_BASE = "https://alkalimakersuite-pa.clients6.google.com/$rpc/google.internal.alkali.applications.makersuite.v1.MakerSuiteService"
STREAMING_BASE = "https://webchannel-alkalimakersuite-pa.clients6.google.com"
_REST_BASE = "https://generativelanguage.googleapis.com/v1beta"

# Confirmed API keys (rotate via GenerateCloudApiKey)
# v1.61.0 [2026-06-13] — move hardcoded AI Studio API keys to env
# Keys are read from env vars GOOGLE_AISTUDIO_KEY_1..5 (comma-separated
# GOOGLE_AISTUDIO_KEYS also accepted). Empty entries are filtered out so the
# module imports cleanly even when no keys are configured locally.
def _load_aistudio_keys() -> List[str]:
    """Load AI Studio API keys from environment, filtering empties."""
    bulk = os.getenv("GOOGLE_AISTUDIO_KEYS", "")
    if bulk:
        return [k.strip() for k in bulk.split(",") if k.strip()]
    return [
        k
        for k in (
            os.getenv("GOOGLE_AISTUDIO_KEY_1", ""),
            os.getenv("GOOGLE_AISTUDIO_KEY_2", ""),
            os.getenv("GOOGLE_AISTUDIO_KEY_3", ""),
            os.getenv("GOOGLE_AISTUDIO_KEY_4", ""),
            os.getenv("GOOGLE_AISTUDIO_KEY_5", ""),
        )
        if k
    ]


API_KEYS = _load_aistudio_keys()

# Default key used as a fallback argument; empty string when none configured.
_DEFAULT_API_KEY = API_KEYS[0] if API_KEYS else ""


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

    # v1.61.0 [2026-06-13] — default key from env-loaded list (was API_KEYS[0])
    def __init__(self, cookies: dict[str, str], api_key: str = _DEFAULT_API_KEY) -> None:
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
        output_dimensionality: Optional[int] = None,
    ) -> List[float]:
        """Generate an embedding vector for a piece of text (embedContent).

        Supports Gemini Embedding 2 MRL (Matryoshka Representation Learning)
        via the ``output_dimensionality`` parameter for variable-size vectors.

        Args:
            model: Embedding model, e.g. ``"gemini-embedding-001"``.
            content: Text to embed.
            task_type: Embedding task type. One of: RETRIEVAL_QUERY,
                RETRIEVAL_DOCUMENT, SEMANTIC_SIMILARITY, CLASSIFICATION,
                CLUSTERING, QUESTION_ANSWERING, FACT_VERIFICATION,
                CODE_RETRIEVAL_QUERY.
            title: Optional title for RETRIEVAL_DOCUMENT tasks.
            output_dimensionality: MRL output dimensions (768, 1536, or 3072).
                None uses model default (3072 for gemini-embedding-001).

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
        if output_dimensionality is not None:
            body["outputDimensionality"] = output_dimensionality
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

    def log_event(self, event_type: str, payload: Optional[Dict[str, Any]] = None) -> dict:
        """Send a structured log event to AI Studio (Log).

        Args:
            event_type: Event type string.
            payload: Optional event payload.

        Returns:
            Log response dict.
        """
        body: Dict[str, Any] = {"eventType": event_type}
        if payload:
            body["payload"] = payload
        return self._post_safe("Log", body)

    # ──── Code Assistant ────

    def code_assistant_offline(
        self, request: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Run an offline Code Assistant generation (CodeAssistantOffline).

        Args:
            request: Code assistant request payload.

        Returns:
            Code assistant response dict.
        """
        return self._post_safe("CodeAssistantOffline", request)

    def stream_code_assistant_offline_upload(
        self, generation_id: str, chunk: bytes
    ) -> Dict[str, Any]:
        """Upload a chunk for streaming offline code generation (StreamCodeAssistantOfflineGenerationUpload).

        Args:
            generation_id: Generation session ID.
            chunk: Bytes chunk to upload.

        Returns:
            Upload acknowledgement dict.
        """
        body: Dict[str, Any] = {
            "generationId": generation_id,
            "chunk": chunk.hex() if isinstance(chunk, bytes) else chunk,
        }
        return self._post_safe("StreamCodeAssistantOfflineGenerationUpload", body)

    def get_code_assistant_snapshot(
        self, snapshot_id: str
    ) -> Dict[str, Any]:
        """Retrieve a code assistant snapshot (GetCodeAssistantSnapshot).

        Args:
            snapshot_id: Snapshot identifier.

        Returns:
            Snapshot dict.
        """
        return self._post_safe("GetCodeAssistantSnapshot", {"snapshotId": snapshot_id})

    def load_code_assistant_interaction_history(
        self, session_id: str, page_size: int = 20
    ) -> Dict[str, Any]:
        """Load interaction history for a code assistant session (LoadCodeAssistantInteractionHistory).

        Args:
            session_id: Session identifier.
            page_size: Max number of interactions to return.

        Returns:
            Dict with ``interactions`` list.
        """
        return self._post_safe(
            "LoadCodeAssistantInteractionHistory",
            {"sessionId": session_id, "pageSize": page_size},
        )

    def list_code_assistant_configurations(self) -> list[dict]:
        """List available Code Assistant configurations (ListCodeAssistantConfigurations).

        Returns:
            List of configuration dicts.
        """
        return self._post_safe("ListCodeAssistantConfigurations", {}).get(
            "configurations", []
        )

    def list_code_assistant_features(self) -> list[dict]:
        """List enabled Code Assistant features (ListCodeAssistantFeatures).

        Returns:
            List of feature descriptor dicts.
        """
        return self._post_safe("ListCodeAssistantFeatures", {}).get("features", [])

    def list_code_assistant_offline_generations(
        self, page_size: int = 50
    ) -> list[dict]:
        """List offline code generations (ListCodeAssistantOfflineGenerations).

        Args:
            page_size: Max results.

        Returns:
            List of generation dicts.
        """
        return self._post_safe(
            "ListCodeAssistantOfflineGenerations", {"pageSize": page_size}
        ).get("generations", [])

    def list_code_gen_suggestion_cards(
        self, context: str = ""
    ) -> list[dict]:
        """List code generation suggestion cards (ListCodeGenSuggestionCards).

        Args:
            context: Optional context string for filtering suggestions.

        Returns:
            List of suggestion card dicts.
        """
        body: Dict[str, Any] = {}
        if context:
            body["context"] = context
        return self._post_safe("ListCodeGenSuggestionCards", body).get("cards", [])

    def generate_code_assistant_suggestion_chips(
        self, prompt: str, model: str = "gemini-2.5-flash"
    ) -> list[str]:
        """Generate quick-action suggestion chips for a prompt (GenerateCodeAssistantSuggestionChips).

        Args:
            prompt: User prompt to generate chips for.
            model: Model to use.

        Returns:
            List of suggestion chip strings.
        """
        result = self._post_safe(
            "GenerateCodeAssistantSuggestionChips",
            {"prompt": prompt, "model": model},
        )
        return result.get("chips", [])

    # ──── Applet management (extended) ────

    def list_recent_applets(self, limit: int = 20) -> list[dict]:
        """List recently accessed applets (ListRecentApplets).

        Args:
            limit: Max number of applets to return.

        Returns:
            List of applet summary dicts.
        """
        return self._post_safe("ListRecentApplets", {"limit": limit}).get(
            "applets", []
        )

    def store_recent_applet(self, applet_name: str) -> dict:
        """Record an applet as recently used (StoreRecentApplet).

        Args:
            applet_name: Applet resource name (``applets/{id}``).

        Returns:
            Acknowledgement dict.
        """
        return self._post_safe("StoreRecentApplet", {"appletName": applet_name})

    def save_applet(self, applet_name: str, updates: Dict[str, Any]) -> dict:
        """Save / checkpoint an applet's current state (SaveApplet).

        Args:
            applet_name: Applet resource name.
            updates: Fields to persist.

        Returns:
            Updated applet dict.
        """
        return self._post_safe(
            "SaveApplet", {"appletName": applet_name, "updates": updates}
        )

    def list_unset_applet_secrets(self, applet_name: str) -> list[str]:
        """List secret keys that have not yet been set for an applet (ListUnsetAppletSecrets).

        Args:
            applet_name: Applet resource name.

        Returns:
            List of unset secret key names.
        """
        return self._post_safe(
            "ListUnsetAppletSecrets", {"appletName": applet_name}
        ).get("secretKeys", [])

    def provision_and_initialize_applet(
        self, applet_config: Dict[str, Any]
    ) -> dict:
        """Provision cloud resources and initialize a new applet (ProvisionAndInitializeApplet).

        Args:
            applet_config: Applet configuration dict.

        Returns:
            Provisioning status dict.
        """
        return self._post_safe("ProvisionAndInitializeApplet", applet_config)

    # ──── Projects & billing ────

    def list_imported_projects(self, page_size: int = 50) -> list[dict]:
        """List Google Cloud projects imported into AI Studio (ListImportedProjects).

        Args:
            page_size: Max results per page.

        Returns:
            List of project dicts.
        """
        return self._post_safe(
            "ListImportedProjects", {"pageSize": page_size}
        ).get("projects", [])

    def list_promos(self) -> list[dict]:
        """List available promotions / credits for the account (ListPromos).

        Returns:
            List of promo dicts.
        """
        return self._post_safe("ListPromos", {}).get("promos", [])

    # ──── Metrics ────

    def fetch_metric_time_series(
        self,
        metric_name: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        granularity: str = "HOUR",
    ) -> list[dict]:
        """Fetch usage metric time-series data (FetchMetricTimeSeries).

        Args:
            metric_name: Metric identifier (e.g. ``token_count``, ``request_count``).
            start_time: ISO-8601 start timestamp. Defaults to 24 h ago.
            end_time: ISO-8601 end timestamp. Defaults to now.
            granularity: Time bucket size — ``HOUR``, ``DAY``, ``WEEK``.

        Returns:
            List of ``{timestamp, value}`` dicts.
        """
        body: Dict[str, Any] = {
            "metricName": metric_name,
            "granularity": granularity,
        }
        if start_time:
            body["startTime"] = start_time
        if end_time:
            body["endTime"] = end_time
        return self._post_safe("FetchMetricTimeSeries", body).get("dataPoints", [])

    # ──── Alias fixes (naming alignment with MakerSuiteService) ────

    def log(self, event_type: str, payload: Optional[Dict[str, Any]] = None) -> dict:
        """Alias for log_event matching the MakerSuiteService ``Log`` method name."""
        return self.log_event(event_type, payload)

    def stream_code_assistant_offline_generation_upload(
        self, generation_id: str, chunk: bytes
    ) -> Dict[str, Any]:
        """Alias for stream_code_assistant_offline_upload."""
        return self.stream_code_assistant_offline_upload(generation_id, chunk)

    # ──── Streaming (code assistant + speech + video) ────

    def stream_code_assistant_offline_generation(
        self, request: Dict[str, Any]
    ) -> Iterator[str]:
        """Stream an offline code assistant generation (StreamCodeAssistantOfflineGeneration).

        Args:
            request: Code assistant request payload.

        Yields:
            Text chunks as they stream.
        """
        endpoint = f"{GRPC_BASE}/StreamCodeAssistantOfflineGeneration"
        headers = {**self._headers(), "Accept": "text/event-stream"}
        with self._session.post(
            endpoint, json=request, headers=headers, stream=True, timeout=120
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines(decode_unicode=True):
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        if text := chunk.get("text"):
                            yield text
                    except json.JSONDecodeError:
                        continue

    def bidi_generate_content(
        self,
        model: str,
        contents: List[Dict[str, Any]],
        system_instruction: Optional[str] = None,
    ) -> Iterator[str]:
        """Bidirectional streaming generation (BidiGenerateContent).

        Args:
            model: Model name.
            contents: Content turns.
            system_instruction: Optional system prompt.

        Yields:
            Text chunks as they stream.
        """
        body: Dict[str, Any] = {"contents": contents}
        if system_instruction:
            body["systemInstruction"] = {"parts": [{"text": system_instruction}]}
        endpoint = f"{_REST_BASE}/models/{model}:bidiGenerateContent?alt=sse&key={self._api_key}"
        headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
        with self._session.post(
            endpoint, json=body, headers=headers, stream=True, timeout=120
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines(decode_unicode=True):
                if not line.startswith("data: "):
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

    def stream_logs(self, resource_name: str) -> Iterator[str]:
        """Stream build/deployment logs (StreamLogs).

        Args:
            resource_name: Resource name to stream logs for.

        Yields:
            Log line strings.
        """
        endpoint = f"{GRPC_BASE}/StreamLogs"
        headers = {**self._headers(), "Accept": "text/event-stream"}
        with self._session.post(
            endpoint,
            json={"resourceName": resource_name},
            headers=headers,
            stream=True,
            timeout=300,
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines(decode_unicode=True):
                if line.startswith("data: "):
                    try:
                        chunk = json.loads(line[6:])
                        if log_line := chunk.get("logLine"):
                            yield log_line
                    except json.JSONDecodeError:
                        continue

    def stream_extract_video_frames(
        self, video_uri: str, fps: float = 1.0
    ) -> Iterator[Dict[str, Any]]:
        """Stream video frame extraction (StreamExtractVideoFrames).

        Args:
            video_uri: URI of uploaded video file.
            fps: Frames per second to extract.

        Yields:
            Frame dicts with timestamp and imageData.
        """
        endpoint = f"{GRPC_BASE}/StreamExtractVideoFrames"
        headers = {**self._headers(), "Accept": "text/event-stream"}
        with self._session.post(
            endpoint,
            json={"videoUri": video_uri, "fps": fps},
            headers=headers,
            stream=True,
            timeout=300,
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines(decode_unicode=True):
                if line.startswith("data: "):
                    try:
                        yield json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue

    def stream_speech_to_text(
        self, audio_data: bytes, language_code: str = "en-US"
    ) -> Iterator[str]:
        """Stream speech-to-text transcription (StreamSpeechToText).

        Args:
            audio_data: Raw audio bytes.
            language_code: BCP-47 language code.

        Yields:
            Incremental transcript strings.
        """
        import base64 as _b64

        endpoint = f"{GRPC_BASE}/StreamSpeechToText"
        headers = {**self._headers(), "Accept": "text/event-stream"}
        body = {"audioContent": _b64.b64encode(audio_data).decode(), "languageCode": language_code}
        with self._session.post(
            endpoint, json=body, headers=headers, stream=True, timeout=300
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines(decode_unicode=True):
                if line.startswith("data: "):
                    try:
                        chunk = json.loads(line[6:])
                        if transcript := chunk.get("transcript"):
                            yield transcript
                    except json.JSONDecodeError:
                        continue

    # ──── Speech ────

    def gemini_speech_to_text(
        self,
        audio_data: bytes,
        language_code: str = "en-US",
        model: str = "gemini-2.5-flash",
    ) -> str:
        """Transcribe audio using Gemini (GeminiSpeechToText).

        Args:
            audio_data: Raw audio bytes (WAV/MP3/FLAC).
            language_code: BCP-47 language code.
            model: Model to use for transcription.

        Returns:
            Transcription text string.
        """
        import base64 as _b64

        result = self._post_safe("GeminiSpeechToText", {
            "audioContent": _b64.b64encode(audio_data).decode(),
            "languageCode": language_code,
            "model": model,
        })
        return result.get("transcript", "")

    # ──── Embeddings (batch REST) ────

    def batch_embed_contents(
        self,
        model: str,
        texts: List[str],
        task_type: str = "RETRIEVAL_DOCUMENT",
        output_dimensionality: Optional[int] = None,
    ) -> List[List[float]]:
        """Batch generate embeddings for multiple texts (BatchEmbedContents).

        Args:
            model: Embedding model name.
            texts: List of text strings to embed.
            task_type: Embedding task type.
            output_dimensionality: MRL output dimensions (768, 1536, or 3072).
                None uses model default.

        Returns:
            List of embedding vectors (each a list of floats).
        """
        requests_list = []
        for t in texts:
            req: Dict[str, Any] = {
                "model": f"models/{model}",
                "content": {"parts": [{"text": t}]},
                "taskType": task_type,
            }
            if output_dimensionality is not None:
                req["outputDimensionality"] = output_dimensionality
            requests_list.append(req)
        result = self._rest_request(
            "POST",
            f"models/{model}:batchEmbedContents",
            data={"requests": requests_list},
        )
        return [e.get("values", []) for e in result.get("embeddings", [])]

    # ──── Applets (extended) ────

    def update_applet(self, applet_id: str, updates: Dict[str, Any]) -> dict:
        """Update an AI Studio app's configuration (UpdateApplet).

        Args:
            applet_id: App UUID.
            updates: Fields to update.

        Returns:
            Updated applet dict.
        """
        return self._post_safe("UpdateApplet", {"appletId": applet_id, **updates})

    def delete_applet(self, applet_id: str) -> dict:
        """Delete an AI Studio app (DeleteApplet).

        Args:
            applet_id: App UUID.

        Returns:
            Empty dict on success.
        """
        return self._post_safe("DeleteApplet", {"appletId": applet_id})

    def clone_applet(self, applet_id: str, display_name: str = "") -> dict:
        """Clone an existing AI Studio app (CloneApplet).

        Args:
            applet_id: Source app UUID.
            display_name: Name for the clone.

        Returns:
            New applet dict with ID.
        """
        body: Dict[str, Any] = {"appletId": applet_id}
        if display_name:
            body["displayName"] = display_name
        return self._post_safe("CloneApplet", body)

    def undeploy_applet(self, applet_id: str) -> dict:
        """Remove a deployed app from Cloud Run (UndeployApplet).

        Args:
            applet_id: App UUID.

        Returns:
            Undeploy status dict.
        """
        return self._post_safe("UndeployApplet", {"appletId": applet_id})

    # ──── Apps (Studio panel — distinct from applets) ────

    def create_app(self, display_name: str, config: Dict[str, Any]) -> dict:
        """Create a new AI Studio app (CreateApp).

        Args:
            display_name: App name.
            config: App configuration dict.

        Returns:
            Created app dict.
        """
        return self._post_safe("CreateApp", {"displayName": display_name, **config})

    def get_app(self, app_name: str) -> dict:
        """Get an AI Studio app by resource name (GetApp).

        Args:
            app_name: App resource name (``apps/{id}``).

        Returns:
            App dict.
        """
        return self._post_safe("GetApp", {"appName": app_name})

    def list_apps(self, page_size: int = 50) -> list[dict]:
        """List AI Studio apps (ListApps).

        Returns:
            List of app dicts.
        """
        return self._post_safe("ListApps", {"pageSize": page_size}).get("apps", [])

    def update_app(self, app_name: str, updates: Dict[str, Any]) -> dict:
        """Update an AI Studio app (UpdateApp).

        Args:
            app_name: App resource name.
            updates: Fields to update.

        Returns:
            Updated app dict.
        """
        return self._post_safe("UpdateApp", {"appName": app_name, **updates})

    def delete_app(self, app_name: str) -> dict:
        """Delete an AI Studio app (DeleteApp).

        Args:
            app_name: App resource name.

        Returns:
            Empty dict on success.
        """
        return self._post_safe("DeleteApp", {"appName": app_name})

    # ──── Batch jobs ────

    def create_batch_job(
        self, model: str, input_file: str, output_prefix: str = ""
    ) -> dict:
        """Create a batch inference job (CreateBatchJob).

        Args:
            model: Model name for batch inference.
            input_file: Input data file URI.
            output_prefix: GCS prefix for output files.

        Returns:
            Batch job dict with name and state.
        """
        return self._post_safe("CreateBatchJob", {
            "model": model,
            "inputFile": input_file,
            "outputPrefix": output_prefix,
        })

    def get_batch_job(self, job_name: str) -> dict:
        """Get the status of a batch job (GetBatchJob).

        Args:
            job_name: Batch job resource name.

        Returns:
            Batch job dict with state, completedCount, etc.
        """
        return self._post_safe("GetBatchJob", {"jobName": job_name})

    def list_batch_jobs(self, page_size: int = 50) -> list[dict]:
        """List batch inference jobs (ListBatchJobs).

        Returns:
            List of batch job dicts.
        """
        return self._post_safe("ListBatchJobs", {"pageSize": page_size}).get("jobs", [])

    def cancel_batch_job(self, job_name: str) -> dict:
        """Cancel a running batch job (CancelBatchJob).

        Args:
            job_name: Batch job resource name.

        Returns:
            Empty dict on success.
        """
        return self._post_safe("CancelBatchJob", {"jobName": job_name})

    # ──── Cached content ────

    def create_cached_content(
        self,
        model: str,
        contents: List[Dict[str, Any]],
        ttl_seconds: int = 3600,
    ) -> dict:
        """Create a cached content entry for prompt caching (CreateCachedContent).

        Args:
            model: Model to cache content for.
            contents: Content parts to cache.
            ttl_seconds: Cache TTL in seconds.

        Returns:
            Cached content dict with name and expireTime.
        """
        return self._rest_request("POST", "cachedContents", data={
            "model": f"models/{model}",
            "contents": contents,
            "ttl": f"{ttl_seconds}s",
        })

    def get_cached_content(self, name: str) -> dict:
        """Get a cached content entry (GetCachedContent).

        Args:
            name: Cached content name (``cachedContents/{id}``).

        Returns:
            Cached content dict.
        """
        return self._rest_request("GET", name)

    def list_cached_contents(self, page_size: int = 50) -> list[dict]:
        """List all cached content entries (ListCachedContents).

        Returns:
            List of cached content dicts.
        """
        return self._rest_request(
            "GET", "cachedContents", params={"pageSize": page_size}
        ).get("cachedContents", [])

    def update_cached_content(self, name: str, ttl_seconds: int) -> dict:
        """Update the TTL of a cached content entry (UpdateCachedContent).

        Args:
            name: Cached content name.
            ttl_seconds: New TTL in seconds.

        Returns:
            Updated cached content dict.
        """
        return self._rest_request("PATCH", name, data={"ttl": f"{ttl_seconds}s"})

    def delete_cached_content(self, name: str) -> dict:
        """Delete a cached content entry (DeleteCachedContent).

        Args:
            name: Cached content name.

        Returns:
            Empty dict on success.
        """
        return self._rest_request("DELETE", name)

    # ──── Tuned models ────

    def create_tuned_model(
        self,
        display_name: str,
        base_model: str,
        training_data: List[Dict[str, Any]],
    ) -> dict:
        """Start a model tuning job (CreateTunedModel).

        Args:
            display_name: Name for the tuned model.
            base_model: Base model to tune (e.g. ``"gemini-2.0-flash-lite"``).
            training_data: List of training examples.

        Returns:
            Operation dict with operation name.
        """
        return self._rest_request("POST", "tunedModels", data={
            "displayName": display_name,
            "baseModel": base_model,
            "tuningTask": {"trainingData": {"examples": {"examples": training_data}}},
        })

    def get_tuned_model(self, name: str) -> dict:
        """Get a tuned model (GetTunedModel).

        Args:
            name: Tuned model name (``tunedModels/{id}``).

        Returns:
            Tuned model dict.
        """
        return self._rest_request("GET", name)

    def list_tuned_models(self, page_size: int = 50) -> list[dict]:
        """List tuned models (ListTunedModels).

        Returns:
            List of tuned model dicts.
        """
        return self._rest_request(
            "GET", "tunedModels", params={"pageSize": page_size}
        ).get("tunedModels", [])

    def update_tuned_model(self, name: str, updates: Dict[str, Any]) -> dict:
        """Update a tuned model's metadata (UpdateTunedModel).

        Args:
            name: Tuned model name.
            updates: Fields to update (e.g. displayName).

        Returns:
            Updated tuned model dict.
        """
        return self._rest_request("PATCH", name, data=updates)

    def delete_tuned_model(self, name: str) -> dict:
        """Delete a tuned model (DeleteTunedModel).

        Args:
            name: Tuned model name.

        Returns:
            Empty dict on success.
        """
        return self._rest_request("DELETE", name)

    def generate_tuned_content(
        self, model: str, contents: List[Dict[str, Any]]
    ) -> dict:
        """Generate content using a tuned model (GenerateTunedContent).

        Args:
            model: Tuned model name (``tunedModels/{id}``).
            contents: Content turns.

        Returns:
            Generated content dict.
        """
        return self._rest_request("POST", f"{model}:generateContent", data={"contents": contents})

    # ──── Models (extended) ────

    def get_model_card(self, model: str) -> dict:
        """Get the model card for a model (GetModelCard).

        Args:
            model: Model name (e.g. ``"gemini-2.5-flash"``).

        Returns:
            Model card dict with description, capabilities, etc.
        """
        return self._post_safe("GetModelCard", {"model": model})

    def list_model_cards(self, page_size: int = 50) -> list[dict]:
        """List all available model cards (ListModelCards).

        Returns:
            List of model card dicts.
        """
        return self._post_safe("ListModelCards", {"pageSize": page_size}).get("modelCards", [])

    def get_model_capabilities(self, model: str) -> dict:
        """Get capability flags for a model (GetModelCapabilities).

        Args:
            model: Model name.

        Returns:
            Dict of capability flags (supportsStreaming, supportsImages, etc.).
        """
        return self._post_safe("GetModelCapabilities", {"model": model})

    # ──── Operations ────

    def get_operation(self, operation_name: str) -> dict:
        """Poll a long-running operation (GetOperation).

        Args:
            operation_name: Operation resource name (``operations/{id}``).

        Returns:
            Operation dict with done, response/error.
        """
        return self._rest_request("GET", operation_name)

    def list_operations(self, filter_str: str = "", page_size: int = 50) -> list[dict]:
        """List long-running operations (ListOperations).

        Args:
            filter_str: Optional filter string.
            page_size: Max results per page.

        Returns:
            List of operation dicts.
        """
        params: Dict[str, Any] = {"pageSize": page_size}
        if filter_str:
            params["filter"] = filter_str
        return self._rest_request("GET", "operations", params=params).get("operations", [])

    def cancel_operation(self, operation_name: str) -> dict:
        """Cancel a long-running operation (CancelOperation).

        Args:
            operation_name: Operation resource name.

        Returns:
            Empty dict on success.
        """
        return self._rest_request("POST", f"{operation_name}:cancel")

    def delete_operation(self, operation_name: str) -> dict:
        """Delete a completed operation (DeleteOperation).

        Args:
            operation_name: Operation resource name.

        Returns:
            Empty dict on success.
        """
        return self._rest_request("DELETE", operation_name)

    # ──── Corpus / Retrieval ────

    def create_corpus(self, display_name: str) -> dict:
        """Create a semantic retrieval corpus (CreateCorpus).

        Args:
            display_name: Corpus name.

        Returns:
            Created corpus dict with name.
        """
        return self._rest_request("POST", "corpora", data={"displayName": display_name})

    def get_corpus(self, name: str) -> dict:
        """Get a corpus (GetCorpus).

        Args:
            name: Corpus name (``corpora/{id}``).

        Returns:
            Corpus dict.
        """
        return self._rest_request("GET", name)

    def list_corpora(self, page_size: int = 50) -> list[dict]:
        """List all corpora (ListCorpora).

        Returns:
            List of corpus dicts.
        """
        return self._rest_request(
            "GET", "corpora", params={"pageSize": page_size}
        ).get("corpora", [])

    def update_corpus(self, name: str, display_name: str) -> dict:
        """Update a corpus's display name (UpdateCorpus).

        Args:
            name: Corpus name.
            display_name: New display name.

        Returns:
            Updated corpus dict.
        """
        return self._rest_request("PATCH", name, data={"displayName": display_name})

    def delete_corpus(self, name: str) -> dict:
        """Delete a corpus (DeleteCorpus).

        Args:
            name: Corpus name.

        Returns:
            Empty dict on success.
        """
        return self._rest_request("DELETE", name)

    def query_corpus(self, name: str, query: str, results_count: int = 10) -> list[dict]:
        """Semantic search within a corpus (QueryCorpus).

        Args:
            name: Corpus name.
            query: Query text.
            results_count: Max chunks to return.

        Returns:
            List of relevant chunk dicts with score.
        """
        return self._rest_request("POST", f"{name}:query", data={
            "query": query,
            "resultsCount": results_count,
        }).get("relevantChunks", [])

    def create_document(
        self,
        corpus_name: str,
        display_name: str,
        metadata: Optional[List[Dict[str, Any]]] = None,
    ) -> dict:
        """Create a document within a corpus (CreateDocument).

        Args:
            corpus_name: Parent corpus name.
            display_name: Document name.
            metadata: Optional list of custom metadata key-value pairs.

        Returns:
            Created document dict.
        """
        body: Dict[str, Any] = {"displayName": display_name}
        if metadata:
            body["customMetadata"] = metadata
        return self._rest_request("POST", f"{corpus_name}/documents", data=body)

    def get_document(self, name: str) -> dict:
        """Get a document from a corpus (GetDocument).

        Args:
            name: Document name (``corpora/{id}/documents/{id}``).

        Returns:
            Document dict.
        """
        return self._rest_request("GET", name)

    def list_documents(self, corpus_name: str, page_size: int = 50) -> list[dict]:
        """List documents in a corpus (ListDocuments).

        Args:
            corpus_name: Parent corpus name.
            page_size: Max results.

        Returns:
            List of document dicts.
        """
        return self._rest_request(
            "GET", f"{corpus_name}/documents", params={"pageSize": page_size}
        ).get("documents", [])

    def delete_document(self, name: str) -> dict:
        """Delete a document (DeleteDocument).

        Args:
            name: Document name.

        Returns:
            Empty dict on success.
        """
        return self._rest_request("DELETE", name)

    def query_document(self, name: str, query: str, results_count: int = 10) -> list[dict]:
        """Semantic search within a specific document (QueryDocument).

        Args:
            name: Document name.
            query: Query text.
            results_count: Max chunks to return.

        Returns:
            List of relevant chunk dicts.
        """
        return self._rest_request("POST", f"{name}:query", data={
            "query": query,
            "resultsCount": results_count,
        }).get("relevantChunks", [])

    def create_chunk(
        self,
        document_name: str,
        data: str,
        metadata: Optional[List[Dict[str, Any]]] = None,
    ) -> dict:
        """Create a chunk within a document (CreateChunk).

        Args:
            document_name: Parent document name.
            data: Text content of the chunk.
            metadata: Optional custom metadata.

        Returns:
            Created chunk dict.
        """
        body: Dict[str, Any] = {"data": {"stringValue": data}}
        if metadata:
            body["customMetadata"] = metadata
        return self._rest_request("POST", f"{document_name}/chunks", data=body)

    def get_chunk(self, name: str) -> dict:
        """Get a chunk (GetChunk).

        Args:
            name: Chunk name.

        Returns:
            Chunk dict.
        """
        return self._rest_request("GET", name)

    def list_chunks(self, document_name: str, page_size: int = 100) -> list[dict]:
        """List chunks in a document (ListChunks).

        Args:
            document_name: Parent document name.
            page_size: Max results.

        Returns:
            List of chunk dicts.
        """
        return self._rest_request(
            "GET", f"{document_name}/chunks", params={"pageSize": page_size}
        ).get("chunks", [])

    def update_chunk(self, name: str, data: str) -> dict:
        """Update a chunk's text content (UpdateChunk).

        Args:
            name: Chunk name.
            data: New text content.

        Returns:
            Updated chunk dict.
        """
        return self._rest_request("PATCH", name, data={"data": {"stringValue": data}})

    def delete_chunk(self, name: str) -> dict:
        """Delete a chunk (DeleteChunk).

        Args:
            name: Chunk name.

        Returns:
            Empty dict on success.
        """
        return self._rest_request("DELETE", name)

    # ──── Datasets ────

    def create_dataset(self, display_name: str, description: str = "") -> dict:
        """Create a new dataset for tuning or evaluation (CreateDataset).

        Args:
            display_name: Dataset name.
            description: Optional description.

        Returns:
            Created dataset dict with name.
        """
        return self._post_safe("CreateDataset", {
            "displayName": display_name,
            "description": description,
        })

    def get_dataset(self, dataset_name: str) -> dict:
        """Get a dataset by name (GetDataset).

        Args:
            dataset_name: Dataset resource name.

        Returns:
            Dataset dict.
        """
        return self._post_safe("GetDataset", {"datasetName": dataset_name})

    def list_datasets(self, page_size: int = 50) -> list[dict]:
        """List all datasets (ListDatasets).

        Returns:
            List of dataset dicts.
        """
        return self._post_safe("ListDatasets", {"pageSize": page_size}).get("datasets", [])

    def update_dataset(self, dataset_name: str, updates: Dict[str, Any]) -> dict:
        """Update a dataset's metadata (UpdateDataset).

        Args:
            dataset_name: Dataset resource name.
            updates: Fields to update.

        Returns:
            Updated dataset dict.
        """
        return self._post_safe("UpdateDataset", {"datasetName": dataset_name, **updates})

    def delete_dataset(self, dataset_name: str) -> dict:
        """Delete a dataset (DeleteDataset).

        Args:
            dataset_name: Dataset resource name.

        Returns:
            Empty dict on success.
        """
        return self._post_safe("DeleteDataset", {"datasetName": dataset_name})

    def import_dataset_items(
        self, dataset_name: str, items: List[Dict[str, Any]]
    ) -> dict:
        """Import items into a dataset (ImportDatasetItems).

        Args:
            dataset_name: Dataset resource name.
            items: List of dataset item dicts.

        Returns:
            Import operation dict.
        """
        return self._post_safe("ImportDatasetItems", {
            "datasetName": dataset_name,
            "items": items,
        })

    def export_dataset_items(self, dataset_name: str, destination: str) -> dict:
        """Export dataset items to a destination (ExportDatasetItems).

        Args:
            dataset_name: Dataset resource name.
            destination: GCS URI or file path for export.

        Returns:
            Export operation dict.
        """
        return self._post_safe("ExportDatasetItems", {
            "datasetName": dataset_name,
            "destination": destination,
        })

    def annotate_dataset(
        self, dataset_name: str, annotation_config: Dict[str, Any]
    ) -> dict:
        """Add annotations to a dataset (AnnotateDataset).

        Args:
            dataset_name: Dataset resource name.
            annotation_config: Annotation configuration dict.

        Returns:
            Operation dict.
        """
        return self._post_safe("AnnotateDataset", {
            "datasetName": dataset_name,
            **annotation_config,
        })

    # ──── GitHub integration ────

    def create_git_hub_repository(
        self, applet_id: str, repo_name: str, private: bool = True
    ) -> dict:
        """Create a GitHub repository linked to an applet (CreateGitHubRepository).

        Args:
            applet_id: App UUID.
            repo_name: Repository name.
            private: Whether the repo is private.

        Returns:
            Dict with repoUrl.
        """
        return self._post_safe("CreateGitHubRepository", {
            "appletId": applet_id,
            "repoName": repo_name,
            "private": private,
        })

    def get_git_hub_repository(self, applet_id: str) -> dict:
        """Get the linked GitHub repository for an applet (GetGitHubRepository).

        Args:
            applet_id: App UUID.

        Returns:
            Repository info dict.
        """
        return self._post_safe("GetGitHubRepository", {"appletId": applet_id})

    def sync_git_hub_repository(self, applet_id: str) -> dict:
        """Sync an applet with its GitHub repository (SyncGitHubRepository).

        Args:
            applet_id: App UUID.

        Returns:
            Sync status dict.
        """
        return self._post_safe("SyncGitHubRepository", {"appletId": applet_id})

    # ──── Safety ────

    def check_safety(self, text: str, model: str = "gemini-2.5-flash") -> dict:
        """Check text for safety policy violations (CheckSafety).

        Args:
            text: Text to check.
            model: Model to use for safety evaluation.

        Returns:
            Dict with safetyRatings and blocked flag.
        """
        return self._post_safe("CheckSafety", {"text": text, "model": model})

    def get_safety_settings(self) -> dict:
        """Get current safety filter settings (GetSafetySettings).

        Returns:
            Dict with per-category thresholds.
        """
        return self._post_safe("GetSafetySettings", {})

    def update_safety_settings(self, settings: Dict[str, Any]) -> dict:
        """Update safety filter thresholds (UpdateSafetySettings).

        Args:
            settings: Dict mapping category to threshold level.

        Returns:
            Updated settings dict.
        """
        return self._post_safe("UpdateSafetySettings", settings)

    # ──── Notifications ────

    def list_notifications(self, page_size: int = 50) -> list[dict]:
        """List account notifications (ListNotifications).

        Returns:
            List of notification dicts with id, title, body, read.
        """
        return self._post_safe("ListNotifications", {"pageSize": page_size}).get("notifications", [])

    def mark_notification_read(self, notification_id: str) -> dict:
        """Mark a notification as read (MarkNotificationRead).

        Args:
            notification_id: Notification ID.

        Returns:
            Empty dict on success.
        """
        return self._post_safe("MarkNotificationRead", {"notificationId": notification_id})

    def dismiss_notification(self, notification_id: str) -> dict:
        """Dismiss a notification (DismissNotification).

        Args:
            notification_id: Notification ID.

        Returns:
            Empty dict on success.
        """
        return self._post_safe("DismissNotification", {"notificationId": notification_id})

    # ──── Prompts (extended) ────

    def get_prompt(self, prompt_name: str) -> dict:
        """Get a saved prompt by resource name (GetPrompt).

        Args:
            prompt_name: Prompt resource name (``prompts/{id}``).

        Returns:
            Prompt dict.
        """
        return self._post_safe("GetPrompt", {"promptName": prompt_name})

    def update_prompt(self, prompt_name: str, updates: Dict[str, Any]) -> dict:
        """Update a prompt template (UpdatePrompt).

        Args:
            prompt_name: Prompt resource name.
            updates: Fields to update (displayName, text, model).

        Returns:
            Updated prompt dict.
        """
        return self._post_safe("UpdatePrompt", {"promptName": prompt_name, **updates})

    def delete_prompt(self, prompt_name: str) -> dict:
        """Delete a prompt template (DeletePrompt).

        Args:
            prompt_name: Prompt resource name.

        Returns:
            Empty dict on success.
        """
        return self._post_safe("DeletePrompt", {"promptName": prompt_name})

    # ──── Sharing / Collaboration ────

    def share_prompt(self, prompt_name: str, share_with: List[str]) -> dict:
        """Share a prompt with other users (SharePrompt).

        Args:
            prompt_name: Prompt resource name.
            share_with: List of email addresses to share with.

        Returns:
            Share status dict.
        """
        return self._post_safe("SharePrompt", {
            "promptName": prompt_name,
            "shareWith": share_with,
        })

    def get_shared_prompt(self, share_id: str) -> dict:
        """Get a prompt shared by another user (GetSharedPrompt).

        Args:
            share_id: Share identifier or URL token.

        Returns:
            Shared prompt dict.
        """
        return self._post_safe("GetSharedPrompt", {"shareId": share_id})

    def list_shared_prompts(self, page_size: int = 50) -> list[dict]:
        """List prompts shared with the current user (ListSharedPrompts).

        Returns:
            List of shared prompt dicts.
        """
        return self._post_safe("ListSharedPrompts", {"pageSize": page_size}).get("sharedPrompts", [])

    # ──── User settings ────

    def get_user_settings(self) -> dict:
        """Get account-level user settings (GetUserSettings).

        Returns:
            User settings dict.
        """
        return self._post_safe("GetUserSettings", {})

    def update_user_settings(self, settings: Dict[str, Any]) -> dict:
        """Update account-level user settings (UpdateUserSettings).

        Args:
            settings: Settings key-value pairs to update.

        Returns:
            Updated settings dict.
        """
        return self._post_safe("UpdateUserSettings", settings)

    def get_usage_metadata(self) -> dict:
        """Get usage statistics and quota metadata (GetUsageMetadata).

        Returns:
            Dict with tokenUsage, requestCounts, quotaLimits.
        """
        return self._post_safe("GetUsageMetadata", {})

    # ──── Infrastructure ────

    def check_quota(self, model: str = "") -> dict:
        """Check quota availability for a model or globally (CheckQuota).

        Args:
            model: Optional model name to check quota for.

        Returns:
            Dict with quotaUsed, quotaLimit, available.
        """
        body: Dict[str, Any] = {}
        if model:
            body["model"] = model
        return self._post_safe("CheckQuota", body)

    def get_billing_info(self) -> dict:
        """Get billing account and credit information (GetBillingInfo).

        Returns:
            Dict with billingAccount, credits, usageThisMonth.
        """
        return self._post_safe("GetBillingInfo", {})

    def fetch_piper_file(self, file_path: str) -> bytes:
        """Fetch an internal Piper filesystem file (FetchPiperFile).

        Args:
            file_path: Piper file path.

        Returns:
            Raw file bytes.
        """
        import base64 as _b64

        result = self._post_safe("FetchPiperFile", {"filePath": file_path})
        content = result.get("content", "")
        if isinstance(content, str) and content:
            try:
                return _b64.b64decode(content)
            except Exception:
                return content.encode()
        return b""

    def download_build_artifacts(self, build_id: str) -> bytes:
        """Download build artifacts for a deployment (DownloadBuildArtifacts).

        Args:
            build_id: Build or deployment ID.

        Returns:
            Raw artifact bytes (typically a zip archive).
        """
        import base64 as _b64

        result = self._post_safe("DownloadBuildArtifacts", {"buildId": build_id})
        content = result.get("content", "")
        if isinstance(content, str) and content:
            try:
                return _b64.b64decode(content)
            except Exception:
                return content.encode()
        return b""

    def download_file(self, file_name: str) -> bytes:
        """Download a previously uploaded file (DownloadFile).

        Args:
            file_name: File resource name (``files/{id}``).

        Returns:
            Raw file bytes.
        """
        import base64 as _b64

        result = self._rest_request("GET", f"{file_name}:download")
        content = result.get("content", "")
        if isinstance(content, str) and content:
            try:
                return _b64.b64decode(content)
            except Exception:
                return content.encode()
        return b""

    def create_cloud_project(self, display_name: str, billing_account: str = "") -> dict:
        """Create a new GCP project linked to AI Studio (CreateCloudProject).

        Args:
            display_name: Project display name.
            billing_account: Billing account ID to link.

        Returns:
            Created project dict with projectId.
        """
        body: Dict[str, Any] = {"displayName": display_name}
        if billing_account:
            body["billingAccount"] = billing_account
        return self._post_safe("CreateCloudProject", body)

    # ──── Image (extended) ────

    def edit_image(
        self,
        image_data: bytes,
        prompt: str,
        model: str = "imagen-3.0",
    ) -> bytes:
        """Edit an image with a text instruction (EditImage).

        Args:
            image_data: Source image bytes.
            prompt: Edit instruction.
            model: Imagen model to use.

        Returns:
            Edited image bytes (PNG).
        """
        import base64 as _b64

        result = self._post_safe("EditImage", {
            "image": _b64.b64encode(image_data).decode(),
            "prompt": prompt,
            "model": model,
        })
        img_b64 = result.get("imageData", "")
        return _b64.b64decode(img_b64) if img_b64 else b""

    def generate_image_from_text(
        self, prompt: str, model: str = "imagen-3.0", count: int = 1
    ) -> List[bytes]:
        """Generate images from a text prompt (GenerateImageFromText).

        Args:
            prompt: Image description.
            model: Imagen model to use.
            count: Number of images to generate (1–4).

        Returns:
            List of image bytes (PNG).
        """
        import base64 as _b64

        result = self._post_safe("GenerateImageFromText", {
            "prompt": prompt,
            "model": model,
            "count": count,
        })
        return [_b64.b64decode(img.get("imageData", "")) for img in result.get("images", [])]

    def upscale_image(self, image_data: bytes, scale: int = 2) -> bytes:
        """Upscale an image (UpscaleImage).

        Args:
            image_data: Source image bytes.
            scale: Upscale factor (2 or 4).

        Returns:
            Upscaled image bytes (PNG).
        """
        import base64 as _b64

        result = self._post_safe("UpscaleImage", {
            "image": _b64.b64encode(image_data).decode(),
            "scale": scale,
        })
        img_b64 = result.get("imageData", "")
        return _b64.b64decode(img_b64) if img_b64 else b""

    # ──── Structured Output ────

    # v1.57.0 [2026-03-26] — Gemini structured output via google.genai SDK
    # CONNECTS: google.genai Client, Gemini 2.5 Flash (or any model supporting JSON schema)
    # CALLED BY: engine.nexus.knowledge_forge, engine.nexus.schemas consumers
    # EMITS: Parsed Python object matching the provided JSON schema
    def generate_structured(
        self,
        prompt: str,
        schema: dict,
        model: str = "gemini-2.5-flash",
        system_instruction: str = "",
    ) -> Any:
        """Generate content with JSON schema enforcement.

        Uses the google.genai SDK for native structured output. The model is
        forced to produce JSON matching the provided schema, eliminating the
        need for regex-based extraction of fenced JSON from markdown responses.

        Args:
            prompt: User prompt text.
            schema: JSON schema dict (Gemini format with STRING/NUMBER/OBJECT/ARRAY types).
            model: Model to use for generation.
            system_instruction: Optional system instruction text.

        Returns:
            Parsed Python object (dict, list, etc.) matching the schema.

        Raises:
            Exception: On API failure or JSON parse error.
        """
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self._api_key)

        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
        )
        if system_instruction:
            config.system_instruction = system_instruction

        result = client.models.generate_content(
            model=model,
            contents=prompt,
            config=config,
        )

        return json.loads(result.text)


# ──── Singleton ────

_client: Optional[AIStudioClient] = None


def get_aistudio_client(cookies: Optional[dict] = None, api_key: str = _DEFAULT_API_KEY) -> AIStudioClient:
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


# v1.57.0 [2026-03-26] — Module-level convenience for Gemini structured output
def generate_structured(prompt: str, schema: dict, **kwargs: Any) -> Any:
    """Module-level convenience for structured output via Gemini.

    Creates/reuses the singleton AIStudioClient and calls generate_structured().
    Accepts all keyword arguments that AIStudioClient.generate_structured() does
    (model, system_instruction).

    Args:
        prompt: User prompt text.
        schema: JSON schema dict (Gemini format).
        **kwargs: Passed through to AIStudioClient.generate_structured().

    Returns:
        Parsed Python object matching the schema.
    """
    client = get_aistudio_client()
    return client.generate_structured(prompt, schema, **kwargs)
