"""Colab Tunnel Server — deploys a FastAPI inference server on Colab with tunnel access.

Supports cloudflare (free, no account) and ngrok tunnels.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import requests

from engine.integrations.colab_client import ColabClient

logger = logging.getLogger(__name__)

# ──── Cell code strings ────────────────────────────────────────────────────────

SETUP_CELL = """
import subprocess
subprocess.run(["pip", "install", "fastapi", "uvicorn", "pyngrok", "-q"], capture_output=True)
print("DEPS_INSTALLED")
"""

SERVER_CELL = """
import threading, json, os
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import uvicorn

app = FastAPI(title="CosySim Colab Server")

@app.get("/health")
async def health():
    return {"status": "ok", "runtime": "colab"}

@app.post("/infer")
async def infer(payload: dict):
    try:
        from google.colab import ai as colab_ai
        model = payload.get("model", "gemini-2.5-flash-exp")
        prompt = payload["prompt"]
        temperature = payload.get("temperature", 0.7)
        max_tokens = payload.get("max_tokens", 2048)
        result = colab_ai.models.generate_text(
            model=model, 
            prompt=prompt,
            temperature=temperature,
            max_output_tokens=max_tokens
        )
        return {"response": result.text, "model": model, "status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/chat")
async def chat(payload: dict):
    try:
        from google.colab import ai as colab_ai
        model = payload.get("model", "gemini-2.5-flash-exp")
        messages = payload["messages"]
        result = colab_ai.models.generate_content(model=model, contents=messages)
        return {"response": result.text, "model": model, "status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/embed")
async def embed(payload: dict):
    try:
        from google.colab import ai as colab_ai
        texts = payload["texts"]
        model = payload.get("model", "text-embedding-004")
        embeddings = [colab_ai.models.embed_content(model=model, content=t).embedding for t in texts]
        return {"embeddings": embeddings, "model": model, "status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/execute")
async def execute_code(payload: dict):
    import subprocess, sys
    code = payload["code"]
    timeout = payload.get("timeout", 60)
    try:
        result = subprocess.run([sys.executable, "-c", code], 
                               capture_output=True, text=True, timeout=timeout)
        return {"stdout": result.stdout, "stderr": result.stderr, 
                "returncode": result.returncode, "status": "ok"}
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": "Timeout", "returncode": -1, "status": "timeout"}

def _start_server():
    uvicorn.run(app, host="0.0.0.0", port=8765, log_level="error")

_server_thread = threading.Thread(target=_start_server, daemon=True)
_server_thread.start()
import time; time.sleep(2)
print("COSYSIM_SERVER_READY:8765")
"""

TUNNEL_CELL_NGROK = """
from pyngrok import ngrok
import os
authtoken = os.environ.get("NGROK_AUTHTOKEN", "")
if authtoken:
    ngrok.set_auth_token(authtoken)
tunnel = ngrok.connect(8765, "http")
print(f"COSYSIM_TUNNEL_URL:{tunnel.public_url}")
"""

TUNNEL_CELL_CLOUDFLARE = """
import subprocess, threading, re, time

proc = subprocess.Popen(
    ["cloudflared", "tunnel", "--url", "http://localhost:8765", "--no-autoupdate"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
)

tunnel_url = None
for line in proc.stdout:
    match = re.search(r"https://[a-z0-9-]+\\.trycloudflare\\.com", line)
    if match:
        tunnel_url = match.group(0)
        break

if tunnel_url:
    print(f"COSYSIM_TUNNEL_URL:{tunnel_url}")
else:
    print("TUNNEL_FAILED")
"""

INSTALL_CLOUDFLARE_CELL = """
import subprocess
subprocess.run(["wget", "-q", 
    "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
    "-O", "/usr/local/bin/cloudflared"], check=True)
subprocess.run(["chmod", "+x", "/usr/local/bin/cloudflared"], check=True)
print("CLOUDFLARED_INSTALLED")
"""

# ──── Data model ──────────────────────────────────────────────────────────────


@dataclass
class TunnelSession:
    """Active Colab tunnel session.

    Attributes:
        account_name: Name of the Google account hosting this session.
        tunnel_url: Public tunnel URL (e.g. https://xyz.trycloudflare.com).
        tunnel_type: "cloudflare" or "ngrok".
        runtime_url: Colab runtime base URL.
        kernel_id: Jupyter kernel UUID.
        session_id: Jupyter session UUID.
        proxy_token: JWT proxy token for the Colab runtime.
        hardware: GPU hardware type (T4, A100, H100, etc.).
        started_at: Unix timestamp of deployment.
        last_health_check: Unix timestamp of last health check.
        healthy: Whether the session is currently healthy.
        available_models: List of models available via this session.
    """

    account_name: str
    tunnel_url: str
    tunnel_type: str
    runtime_url: str
    kernel_id: str
    session_id: str
    proxy_token: str
    hardware: str
    started_at: float
    last_health_check: float
    healthy: bool = True
    available_models: List[str] = field(default_factory=list)


# ──── Server ──────────────────────────────────────────────────────────────────


class ColabTunnelServer:
    """Manages deployment of FastAPI inference servers on Colab runtimes.

    Args:
        colab_client: Default ColabClient to use for deployments.
        tunnel_type: Tunnel provider — "cloudflare" (default) or "ngrok".
        ngrok_token: Optional ngrok authtoken for authenticated tunnels.
    """

    def __init__(
        self,
        colab_client: Optional[ColabClient],
        tunnel_type: str = "cloudflare",
        ngrok_token: Optional[str] = None,
    ) -> None:
        self._colab_client = colab_client
        self._tunnel_type = tunnel_type
        self._ngrok_token = ngrok_token
        self._sessions: Dict[str, TunnelSession] = {}

    # ──── Helpers ─────────────────────────────────────────────────────────────

    def _get_client(self, account_name: Optional[str] = None) -> Optional[ColabClient]:
        """Return ColabClient for account_name, falling back to default client.

        Args:
            account_name: Specific account name, or None for default.

        Returns:
            ColabClient, or None if unavailable.
        """
        if account_name:
            try:
                from engine.integrations.colab_client import get_colab_client
                client = get_colab_client(account_name)
                if client is not None:
                    return client
            except Exception as exc:
                logger.debug("Could not get client for %s: %s", account_name, exc)
        return self._colab_client

    def _detect_hardware(self, client: ColabClient) -> str:
        """Detect the hardware tier from the Colab runtime.

        Args:
            client: Active ColabClient.

        Returns:
            Hardware string like "T4" or "A100".
        """
        try:
            info = client.get_user_info()
            all_hw: List[str] = []
            for v in (info.get("pro_tiers") or {}).values():
                if isinstance(v, list):
                    all_hw.extend(v)
            for v in (info.get("free_tiers") or {}).values():
                if isinstance(v, list):
                    all_hw.extend(v)
            if all_hw:
                return all_hw[0]
        except Exception as exc:
            logger.debug("Could not detect hardware: %s", exc)
        return "T4"

    @staticmethod
    def _parse_tunnel_url(output: str) -> Optional[str]:
        """Extract tunnel URL from cell output.

        Args:
            output: Raw cell output string.

        Returns:
            Tunnel URL string, or None if not found.
        """
        for line in output.splitlines():
            if "COSYSIM_TUNNEL_URL:" in line:
                return line.split("COSYSIM_TUNNEL_URL:", 1)[1].strip()
        return None

    # ──── Deploy ──────────────────────────────────────────────────────────────

    def deploy(self, account_name: Optional[str] = None) -> TunnelSession:
        """Deploy a FastAPI inference server on Colab with a public tunnel.

        Executes setup, server, and tunnel cells in sequence.

        Args:
            account_name: Google account to deploy on, or None for default.

        Returns:
            TunnelSession with tunnel URL and metadata.

        Raises:
            RuntimeError: If no client available, runtime not found, or tunnel fails.
        """
        client = self._get_client(account_name)
        if client is None:
            raise RuntimeError(
                "No Colab client available. "
                "Import an account with: pool.import_from_har(har_path, 'name', ['colab'])"
            )

        # 1. Get runtime
        runtime_url, proxy_token = client.get_or_assign_runtime()

        # 2. Create kernel session
        session_id, kernel_id = client.create_kernel_session(runtime_url, proxy_token)

        logger.info("Deploying CosySim server on kernel %s", kernel_id)

        # 3. Install dependencies
        result = client.execute_code(runtime_url, kernel_id, proxy_token, SETUP_CELL, timeout=180)
        output = result.get("output", "")
        if "DEPS_INSTALLED" not in output:
            logger.warning("Setup cell output did not confirm deps: %s", output[:200])

        # 4. Start FastAPI server
        result = client.execute_code(runtime_url, kernel_id, proxy_token, SERVER_CELL, timeout=60)
        server_output = result.get("output", "")
        if "COSYSIM_SERVER_READY" not in server_output:
            raise RuntimeError(
                f"CosySim server did not start. Output: {server_output[:300]}"
            )

        # 5. Start tunnel
        if self._tunnel_type == "cloudflare":
            client.execute_code(
                runtime_url, kernel_id, proxy_token, INSTALL_CLOUDFLARE_CELL, timeout=120
            )
            tunnel_result = client.execute_code(
                runtime_url, kernel_id, proxy_token, TUNNEL_CELL_CLOUDFLARE, timeout=120
            )
        else:
            ngrok_code = TUNNEL_CELL_NGROK
            if self._ngrok_token:
                ngrok_code = (
                    f'import os; os.environ["NGROK_AUTHTOKEN"] = "{self._ngrok_token}"\n'
                    + TUNNEL_CELL_NGROK
                )
            tunnel_result = client.execute_code(
                runtime_url, kernel_id, proxy_token, ngrok_code, timeout=60
            )

        tunnel_output = tunnel_result.get("output", "")

        # 6. Parse tunnel URL
        tunnel_url = self._parse_tunnel_url(tunnel_output)
        if not tunnel_url:
            raise RuntimeError(
                f"Could not parse COSYSIM_TUNNEL_URL from output: {tunnel_output[:300]}"
            )

        # 7. Health check
        hardware = self._detect_hardware(client)
        healthy = False
        try:
            resp = requests.get(f"{tunnel_url}/health", timeout=10)
            healthy = resp.status_code == 200
        except Exception as exc:
            logger.warning("Initial health check failed for %s: %s", tunnel_url, exc)

        # 8. Register session
        resolved_account = account_name or getattr(
            getattr(client, "_account", None), "name", "default"
        )
        session = TunnelSession(
            account_name=resolved_account,
            tunnel_url=tunnel_url,
            tunnel_type=self._tunnel_type,
            runtime_url=runtime_url,
            kernel_id=kernel_id,
            session_id=session_id,
            proxy_token=proxy_token,
            hardware=hardware,
            started_at=time.time(),
            last_health_check=time.time(),
            healthy=healthy,
        )

        self._sessions[session_id] = session
        logger.info("Tunnel session registered: %s (%s)", tunnel_url, hardware)
        return session

    # ──── Health ──────────────────────────────────────────────────────────────

    def health_check(self, session: TunnelSession) -> bool:
        """Check if the tunnel server is reachable.

        Args:
            session: TunnelSession to check.

        Returns:
            True if server responded with 200 OK.
        """
        try:
            resp = requests.get(f"{session.tunnel_url}/health", timeout=10)
            session.healthy = resp.status_code == 200
        except Exception as exc:
            logger.debug("Health check failed for %s: %s", session.tunnel_url, exc)
            session.healthy = False
        session.last_health_check = time.time()
        return session.healthy

    # ──── Inference ───────────────────────────────────────────────────────────

    def infer(
        self,
        session: TunnelSession,
        prompt: str,
        model: str = "gemini-2.5-flash-exp",
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str:
        """Run text inference via the tunnel server.

        Args:
            session: Active TunnelSession.
            prompt: Text prompt.
            model: Gemini model identifier.
            temperature: Sampling temperature.
            max_tokens: Maximum output tokens.

        Returns:
            Response text.
        """
        try:
            resp = requests.post(
                f"{session.tunnel_url}/infer",
                json={
                    "prompt": prompt,
                    "model": model,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
                timeout=60,
            )
            resp.raise_for_status()
            return resp.json().get("response", "")
        except Exception as exc:
            logger.error("Tunnel infer failed: %s", exc)
            raise

    def chat(
        self,
        session: TunnelSession,
        messages: List[Dict],
        model: str = "gemini-2.5-flash-exp",
    ) -> str:
        """Run a multi-turn chat via the tunnel server.

        Args:
            session: Active TunnelSession.
            messages: List of message dicts.
            model: Gemini model identifier.

        Returns:
            Response text.
        """
        try:
            resp = requests.post(
                f"{session.tunnel_url}/chat",
                json={"messages": messages, "model": model},
                timeout=60,
            )
            resp.raise_for_status()
            return resp.json().get("response", "")
        except Exception as exc:
            logger.error("Tunnel chat failed: %s", exc)
            raise

    def embed(self, session: TunnelSession, texts: List[str]) -> List[List[float]]:
        """Generate text embeddings via the tunnel server.

        Args:
            session: Active TunnelSession.
            texts: List of strings to embed.

        Returns:
            List of embedding vectors.
        """
        try:
            resp = requests.post(
                f"{session.tunnel_url}/embed",
                json={"texts": texts},
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json().get("embeddings", [])
        except Exception as exc:
            logger.error("Tunnel embed failed: %s", exc)
            raise

    def execute(self, session: TunnelSession, code: str, timeout: int = 60) -> Dict:
        """Execute Python code on the Colab runtime via the tunnel server.

        Args:
            session: Active TunnelSession.
            code: Python source code.
            timeout: Execution timeout in seconds.

        Returns:
            Dict with stdout, stderr, returncode, status.
        """
        try:
            resp = requests.post(
                f"{session.tunnel_url}/execute",
                json={"code": code, "timeout": timeout},
                timeout=timeout + 10,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.error("Tunnel execute failed: %s", exc)
            raise

    # ──── Lifecycle ───────────────────────────────────────────────────────────

    def teardown(self, session: TunnelSession) -> None:
        """Shut down a tunnel session and close the kernel.

        Args:
            session: TunnelSession to tear down.
        """
        try:
            client = self._get_client(session.account_name)
            if client is not None:
                client.close_session(
                    session.runtime_url, session.session_id, session.proxy_token
                )
        except Exception as exc:
            logger.warning("Could not close kernel session %s: %s", session.session_id, exc)

        self._sessions.pop(session.session_id, None)
        logger.info("Torn down tunnel session %s", session.tunnel_url)

    def get_active_sessions(self) -> List[TunnelSession]:
        """Return all healthy tunnel sessions after running health checks.

        Returns:
            List of currently healthy TunnelSession objects.
        """
        result = []
        for session in list(self._sessions.values()):
            self.health_check(session)
            if session.healthy:
                result.append(session)
        return result


# ──── Singleton ───────────────────────────────────────────────────────────────

_tunnel_server_instance: Optional[ColabTunnelServer] = None


def get_tunnel_server() -> ColabTunnelServer:
    """Get or create the singleton ColabTunnelServer.

    Returns:
        Singleton ColabTunnelServer instance.
    """
    global _tunnel_server_instance
    if _tunnel_server_instance is None:
        from engine.integrations.colab_client import get_colab_client
        _tunnel_server_instance = ColabTunnelServer(colab_client=get_colab_client())
    return _tunnel_server_instance
