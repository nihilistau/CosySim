import express from "express";
import { createServer as createViteServer } from "vite";
import { db } from "./src/db.js";
import * as cheerio from "cheerio";
import * as fs from "fs";
import * as path from "path";
import puppeteer, { type Browser, type Page, type HTTPRequest, type HTTPResponse } from "puppeteer-core";
import { JSDOM } from "jsdom";
import { Readability } from "@mozilla/readability";

// ── Browser session store ─────────────────────────────────────────────────────
const CHROME_PATH = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
// Persistent Chrome profiles per account — survives restarts, keeps sessions/cookies
const CHROME_PROFILES_DIR = path.join(process.cwd(), "data", "chrome_profiles");
const BROWSER_W = 1280, BROWSER_H = 800;

interface HarEntry {
  startedDateTime: string;
  time: number;
  request: {
    method: string; url: string; httpVersion: string;
    headers: { name: string; value: string }[];
    cookies: { name: string; value: string }[];
    queryString: { name: string; value: string }[];
    postData?: { mimeType: string; text: string };
    headersSize: number; bodySize: number;
  };
  response: {
    status: number; statusText: string; httpVersion: string;
    headers: { name: string; value: string }[];
    cookies: { name: string; value: string }[];
    content: { size: number; mimeType: string; text?: string };
    redirectURL: string; headersSize: number; bodySize: number;
  };
  timings: { send: number; wait: number; receive: number };
}

interface BrowserSession {
  browser: Browser;
  page: Page;
  harEntries: HarEntry[];
  requestTimings: Map<string, number>;
  started: number;
  account: string;
}

const browserSessions = new Map<string, BrowserSession>();

function sessionId(): string {
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

function headersToHar(headers: Record<string, string>): { name: string; value: string }[] {
  return Object.entries(headers).map(([name, value]) => ({ name, value }));
}

async function startServer() {
  const app = express();
  const PORT = process.env.PORT ? parseInt(process.env.PORT) : 5590;

  app.use(express.json());

  // API routes
  app.get("/api/health", (req, res) => {
    res.json({ status: "ok" });
  });

  // Web Search (Wikipedia for demo)
  app.post("/api/search", async (req, res) => {
    try {
      const { query } = req.body;
      const response = await fetch(`https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch=${encodeURIComponent(query)}&utf8=&format=json`);
      const data = await response.json();
      const results = data.query.search.map((r: any) => ({
        title: r.title,
        snippet: r.snippet.replace(/<[^>]*>?/gm, ''), // strip html
        url: `https://en.wikipedia.org/wiki/${encodeURIComponent(r.title)}`
      }));
      res.json({ results });
    } catch (e: any) {
      res.status(500).json({ error: e.message });
    }
  });

  // Fetch URL Content
  app.post("/api/fetch-url", async (req, res) => {
    try {
      const { url } = req.body;
      const response = await fetch(url);
      const html = await response.text();
      const $ = cheerio.load(html);
      $('script, style, noscript, iframe, img, svg').remove();
      const text = $('body').text().replace(/\s+/g, ' ').trim();
      res.json({ text, html });
    } catch (e: any) {
      res.status(500).json({ error: e.message });
    }
  });

  // Database Query
  app.post("/api/db/query", (req, res) => {
    try {
      const { query } = req.body;
      // Only allow SELECT queries for safety
      if (!query.trim().toUpperCase().startsWith("SELECT")) {
        return res.status(400).json({ error: "Only SELECT queries are allowed for safety." });
      }
      const results = db.prepare(query).all();
      res.json({ results });
    } catch (e: any) {
      res.status(500).json({ error: e.message });
    }
  });

  // Notebooks
  app.get("/api/notebooks", (req, res) => {
    const notebooks = db.prepare("SELECT * FROM notebooks ORDER BY updated_at DESC").all();
    res.json(notebooks);
  });

  app.post("/api/notebooks", (req, res) => {
    const { id, name, description } = req.body;
    const stmt = db.prepare("INSERT INTO notebooks (id, name, description) VALUES (?, ?, ?)");
    stmt.run(id, name, description);
    res.json({ success: true });
  });

  app.put("/api/notebooks/:notebookId", (req, res) => {
    const { name, description } = req.body;
    const stmt = db.prepare("UPDATE notebooks SET name = ?, description = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?");
    stmt.run(name, description, req.params.notebookId);
    res.json({ success: true });
  });

  app.delete("/api/notebooks/:notebookId", (req, res) => {
    const stmt = db.prepare("DELETE FROM notebooks WHERE id = ?");
    stmt.run(req.params.notebookId);
    res.json({ success: true });
  });

  // Sources
  app.get("/api/notebooks/:notebookId/sources", (req, res) => {
    const sources = db.prepare("SELECT * FROM sources WHERE notebook_id = ? ORDER BY created_at DESC").all(req.params.notebookId);
    res.json(sources);
  });

  app.post("/api/notebooks/:notebookId/sources", (req, res) => {
    const { id, title, content, type, url } = req.body;
    const stmt = db.prepare("INSERT INTO sources (id, notebook_id, title, content, type, url) VALUES (?, ?, ?, ?, ?, ?)");
    stmt.run(id, req.params.notebookId, title, content, type, url);
    res.json({ success: true });
  });

  app.put("/api/sources/:sourceId", (req, res) => {
    const { title, content } = req.body;
    const stmt = db.prepare("UPDATE sources SET title = ?, content = ? WHERE id = ?");
    stmt.run(title, content, req.params.sourceId);
    res.json({ success: true });
  });

  app.delete("/api/sources/:sourceId", (req, res) => {
    const stmt = db.prepare("DELETE FROM sources WHERE id = ?");
    stmt.run(req.params.sourceId);
    res.json({ success: true });
  });

  // Notes
  app.get("/api/notebooks/:notebookId/notes", (req, res) => {
    const notes = db.prepare("SELECT * FROM notes WHERE notebook_id = ? ORDER BY updated_at DESC").all(req.params.notebookId);
    res.json(notes);
  });

  app.post("/api/notebooks/:notebookId/notes", (req, res) => {
    const { id, title, content } = req.body;
    const stmt = db.prepare("INSERT INTO notes (id, notebook_id, title, content) VALUES (?, ?, ?, ?)");
    stmt.run(id, req.params.notebookId, title, content);
    res.json({ success: true });
  });

  app.put("/api/notes/:noteId", (req, res) => {
    const { title, content } = req.body;
    const stmt = db.prepare("UPDATE notes SET title = ?, content = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?");
    stmt.run(title, content, req.params.noteId);
    res.json({ success: true });
  });

  app.delete("/api/notes/:noteId", (req, res) => {
    const stmt = db.prepare("DELETE FROM notes WHERE id = ?");
    stmt.run(req.params.noteId);
    res.json({ success: true });
  });

  // Workflows
  app.get("/api/notebooks/:notebookId/workflows", (req, res) => {
    const workflows = db.prepare("SELECT * FROM workflows WHERE notebook_id = ? ORDER BY updated_at DESC").all(req.params.notebookId);
    res.json(workflows);
  });

  app.post("/api/notebooks/:notebookId/workflows", (req, res) => {
    const { id, name, nodes, edges } = req.body;
    const stmt = db.prepare("INSERT INTO workflows (id, notebook_id, name, nodes, edges) VALUES (?, ?, ?, ?, ?)");
    stmt.run(id, req.params.notebookId, name, JSON.stringify(nodes), JSON.stringify(edges));
    res.json({ success: true });
  });

  app.put("/api/workflows/:workflowId", (req, res) => {
    const { name, nodes, edges } = req.body;
    const stmt = db.prepare("UPDATE workflows SET name = ?, nodes = ?, edges = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?");
    stmt.run(name, JSON.stringify(nodes), JSON.stringify(edges), req.params.workflowId);
    res.json({ success: true });
  });

  // ── Sidecar helpers ───────────────────────────────────────────────────────
  const CANVAS_SIDECAR = process.env.CANVAS_SIDECAR_URL || "http://localhost:5591";
  const NEXUS_API = "http://localhost:8700";

  async function proxyToSidecar(
    path: string,
    body?: object
  ): Promise<{ data?: any; error?: string; status: number }> {
    try {
      const isGet = !body;
      const res = await fetch(`${CANVAS_SIDECAR}${path}`, {
        method: isGet ? "GET" : "POST",
        headers: { "Content-Type": "application/json" },
        body: isGet ? undefined : JSON.stringify(body),
      });
      const data = await res.json();
      return { data, status: res.status };
    } catch (e: any) {
      return { error: e.message, status: 503 };
    }
  }

  // ── AI Studio ─────────────────────────────────────────────────────────────
  app.post("/api/aistudio/generate", async (req, res) => {
    const result = await proxyToSidecar("/api/generate", req.body);
    if (result.error) {
      res.status(503).json({ error: "Service unavailable", detail: result.error });
    } else {
      res.status(result.status).json(result.data);
    }
  });

  app.get("/api/aistudio/models", async (req, res) => {
    const result = await proxyToSidecar("/api/models");
    if (result.error) {
      res.status(503).json({ error: "Service unavailable", detail: result.error });
    } else {
      res.status(result.status).json(result.data);
    }
  });

  // ── Google Accounts ────────────────────────────────────────────────────────
  app.get("/api/accounts", async (req, res) => {
    try {
      const data = await callPython("engine.integrations.rpc_proxy", "list_accounts_from_dirs", {});
      res.json(data);
    } catch (e: any) {
      res.status(500).json({ error: e.message, accounts: [] });
    }
  });

  app.post("/api/accounts/import-har", async (req, res) => {
    try {
      const { filepath = "", account_name = "", services = [] } = req.body;
      const data = await callPython("engine.integrations.rpc_proxy", "import_har_to_pool", {
        filepath, account_name, services,
      });
      res.json(data);
    } catch (e: any) {
      res.status(500).json({ error: e.message });
    }
  });

  app.post("/api/accounts/import-directory", async (req, res) => {
    try {
      const { directory = "", account_name = "", services = [] } = req.body;
      // Bulk import all HAR files in a directory
      const fs2 = await import("fs");
      const dirFiles = fs2.readdirSync(directory).filter((f: string) => f.endsWith(".har"));
      const results: any[] = [];
      for (const f of dirFiles) {
        const fp = path.join(directory, f);
        try {
          const r = await callPython("engine.integrations.rpc_proxy", "import_har_to_pool", {
            filepath: fp, account_name: account_name || path.basename(directory), services,
          });
          results.push({ file: f, ...r });
        } catch (e: any) {
          results.push({ file: f, error: e.message });
        }
      }
      res.json({ imported: results.length, results });
    } catch (e: any) {
      res.status(500).json({ error: e.message });
    }
  });

  // ── Training Data ──────────────────────────────────────────────────────────
  app.post("/api/training/capture", async (req, res) => {
    const result = await proxyToSidecar("/api/training/capture", req.body);
    if (result.error) {
      res.status(503).json({ error: "Service unavailable", detail: result.error });
    } else {
      res.status(result.status).json(result.data);
    }
  });

  app.get("/api/training/stats", async (req, res) => {
    const result = await proxyToSidecar("/api/training/stats");
    if (result.error) {
      res.status(503).json({ error: "Service unavailable", detail: result.error });
    } else {
      res.status(result.status).json(result.data);
    }
  });

  // ── Nexus Knowledge ────────────────────────────────────────────────────────
  app.post("/api/nexus/search", async (req, res) => {
    try {
      const q = (req.body.q as string) || "";
      const result = await nexusProxy(`/search?q=${encodeURIComponent(q)}`);
      res.json(result);
    } catch { res.json({ results: [] }); }
  });

  app.post("/api/nexus/ask", async (req, res) => {
    try {
      const result = await nexusProxy("/ask", "POST", req.body);
      res.json(result);
    } catch (e: any) { res.status(500).json({ error: e.message }); }
  });

  app.post("/api/nexus/add", async (req, res) => {
    try {
      const result = await nexusProxy("/add", "POST", req.body);
      res.json(result);
    } catch (e: any) { res.status(500).json({ error: e.message }); }
  });

  // ── NotebookLM ─────────────────────────────────────────────────────────────
  app.get("/api/nlm/notebooks", async (req, res) => {
    // Try Nexus KMS first; fall back to local metadata if unavailable
    try {
      const r = await fetch(`${NEXUS_API}/api/nlm/notebooks`);
      if (r.ok) {
        const data = await r.json();
        return res.json(data);
      }
    } catch { /* Nexus KMS down — fall through to Python fallback */ }
    try {
      const data = await callPython("engine.integrations.rpc_proxy", "list_nlm_notebooks", {});
      res.json(data);
    } catch (e: any) {
      res.json({ notebooks: [], error: e.message });
    }
  });

  app.post("/api/nlm/ask", async (req, res) => {
    // Try Nexus KMS first; fall back to direct NLM engine
    try {
      const r = await fetch(`${NEXUS_API}/api/nlm/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(req.body),
      });
      if (r.ok) {
        const data = await r.json();
        return res.status(r.status).json(data);
      }
    } catch { /* Fall through */ }
    try {
      const { question = "", notebook_id = "" } = req.body;
      const data = await callPython("engine.integrations.rpc_proxy", "nlm_ask_python", {
        question, notebook_id,
      });
      res.json(data);
    } catch (e: any) {
      res.status(503).json({ error: "NLM not available", detail: e.message });
    }
  });

  // ── Sidecar Health ─────────────────────────────────────────────────────────
  app.get("/api/sidecar/health", async (req, res) => {
    const result = await proxyToSidecar("/api/health");
    if (result.error) {
      res.status(503).json({ error: "Service unavailable", detail: result.error });
    } else {
      res.status(result.status).json(result.data);
    }
  });

  // ── HAR Import ────────────────────────────────────────────────────────────
  app.post("/api/har/import", async (req, res) => {
    const { harPath, accountId, service } = req.body;
    const result = await proxyToSidecar("/api/accounts/import-har", {
      har_path: harPath,
      account_id: accountId,
      service,
    });
    res.status(result.status).json(result.data || { error: result.error });
  });

  const HAR_DIR = "C:\\Files\\Models\\HAR_Files";
  const HAR_DIR_ALT = "C:\\Files\\Models\\CosySim\\data\\har_files";

  function findHarFile(filename: string): string | null {
    function walk(dir: string): string | null {
      if (!fs.existsSync(dir)) return null;
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) { const r = walk(full); if (r) return r; }
        else if (entry.name === filename) return full;
      }
      return null;
    }
    return walk(HAR_DIR) || walk(HAR_DIR_ALT);
  }

  // ── HAR File Management ───────────────────────────────────────────────────
  app.get("/api/har/list", async (req, res) => {
    try {
      // Use Python parser to list across all HAR directories
      const result = await callPython(
        "engine.integrations.rpc_proxy", "list_har_files_dict", {}
      );
      res.json(result);
    } catch (e: any) { res.status(500).json({ error: e.message }); }
  });

  app.post("/api/har/upload", async (req, res) => {
    try {
      const { filename, content, account_folder } = req.body as {
        filename: string; content: string; account_folder: string;
      };
      const dest = path.join(HAR_DIR, account_folder || "");
      fs.mkdirSync(dest, { recursive: true });
      fs.writeFileSync(path.join(dest, filename), Buffer.from(content, "base64"));
      res.json({ ok: true, path: path.join(dest, filename) });
    } catch (e: any) { res.status(500).json({ error: e.message }); }
  });

  app.post("/api/har/parse", async (req, res) => {
    const result = await proxyToSidecar("/api/har/parse", req.body);
    res.status(result.status).json(result.data || { error: result.error });
  });

  app.post("/api/har/import-account", async (req, res) => {
    try {
      const { path: filepath, account_name, services } = req.body;
      const result = await callPython(
        "engine.integrations.rpc_proxy", "import_har_to_pool",
        { filepath: filepath || req.body.filepath, account_name, services }
      );
      res.json(result);
    } catch (e: any) { res.status(500).json({ error: e.message }); }
  });

  app.get("/api/har/:filename/entries", async (req, res) => {
    try {
      const { filename } = req.params;
      const url_search = (req.query.url_search as string) || (req.query.filter as string) || "";
      const method_filter = (req.query.method as string) || "";
      const limit = parseInt(req.query.limit as string) || 100;
      const offset = parseInt(req.query.offset as string) || 0;

      // Always route through Python — handles large files safely
      const result = await callPython(
        "engine.integrations.rpc_proxy", "get_entries_dict",
        { filename, url_search, method_filter, offset, limit }
      );
      res.json(result);
    } catch (e: any) { res.status(500).json({ error: e.message }); }
  });

  app.get("/api/har/:filename/entry/:idx", async (req, res) => {
    try {
      const result = await callPython(
        "engine.integrations.rpc_proxy", "get_entry_dict",
        { filename: req.params.filename, idx: parseInt(req.params.idx) }
      );
      res.json(result);
    } catch (e: any) { res.status(500).json({ error: e.message }); }
  });

  app.get("/api/har/:filename/analyze", async (req, res) => {
    try {
      const result = await callPython(
        "engine.integrations.rpc_proxy", "analyze_har_dict",
        { filename: req.params.filename }
      );
      res.json(result);
    } catch (e: any) { res.status(500).json({ error: e.message }); }
  });

  // ── RPC Proxy ─────────────────────────────────────────────────────────────
  app.post("/api/rpc/proxy", async (req, res) => {
    try {
      const result = await callPython("engine.integrations.rpc_proxy", "proxy_request", req.body);
      res.json(result);
    } catch (e: any) { res.status(500).json({ error: e.message }); }
  });

  // ── Account Management (compute-aware) ────────────────────────────────────
  app.get("/api/accounts/list", async (req, res) => {
    try {
      const result = await callPython(
        "engine.integrations.rpc_proxy", "list_accounts_with_tiers", {}
      );
      res.json(result);
    } catch (e: any) { res.status(500).json({ error: e.message }); }
  });

  app.post("/api/accounts/configure", async (req, res) => {
    try {
      const result = await callPython("engine.integrations.rpc_proxy", "configure_account", req.body);
      res.json(result);
    } catch (e: any) { res.status(500).json({ error: e.message }); }
  });

  app.delete("/api/accounts/:name", async (req, res) => {
    try {
      const r = await fetch(`${CANVAS_SIDECAR}/api/accounts/${req.params.name}`, { method: "DELETE" });
      const data = await r.json();
      res.status(r.status).json(data);
    } catch (e: any) {
      res.status(503).json({ error: e.message });
    }
  });

  // ── Compute (JIT) ─────────────────────────────────────────────────────────
  app.get("/api/compute/status", async (req, res) => {
    try {
      const result = await callPython("engine.integrations.rpc_proxy", "get_status_dict", {});
      res.json(result);
    } catch (e: any) { res.status(500).json({ error: e.message }); }
  });

  app.post("/api/compute/infer", async (req, res) => {
    try {
      const result = await callPython("engine.integrations.rpc_proxy", "jit_infer_dict", req.body);
      res.json(result);
    } catch (e: any) { res.status(500).json({ error: e.message }); }
  });

  app.post("/api/compute/tunnel/deploy", async (req, res) => {
    try {
      const result = await callPython(
        "engine.integrations.rpc_proxy", "deploy_tunnel_dict", req.body
      );
      res.json(result);
    } catch (e: any) { res.status(500).json({ error: e.message }); }
  });

  app.get("/api/compute/tunnel/list", async (req, res) => {
    try {
      const result = await callPython("engine.integrations.rpc_proxy", "list_sessions_dict", {});
      res.json(result);
    } catch (e: any) { res.status(500).json({ error: e.message }); }
  });

  app.delete("/api/compute/tunnel/:id", async (req, res) => {
    try {
      const result = await callPython(
        "engine.integrations.rpc_proxy", "teardown_by_id",
        { session_id: req.params.id }
      );
      res.json(result);
    } catch (e: any) { res.status(500).json({ error: e.message }); }
  });

  app.get("/api/compute/models", async (req, res) => {
    try {
      const result = await callPython("engine.integrations.rpc_proxy", "get_all_models", {});
      res.json(result);
    } catch (e: any) { res.status(500).json({ error: e.message }); }
  });

  // ── GitHub Copilot ────────────────────────────────────────────────────────
  app.get("/api/copilot/models", async (req, res) => {
    try {
      const result = await callPython(
        "engine.integrations.rpc_proxy", "list_models_dict",
        { account_name: (req.query.account_name as string) || "nihilistcod" }
      );
      res.json(result);
    } catch (e: any) { res.status(500).json({ error: e.message }); }
  });

  app.post("/api/copilot/ask", async (req, res) => {
    try {
      const { prompt, model, account_name } = req.body;
      const result = await new Promise<any>((resolve, reject) => {
        const { spawn } = require("child_process");
        const script = `
import json, sys
sys.path.insert(0, r'C:\\Files\\Models\\CosySim')
args = json.loads(sys.stdin.read())
from engine.integrations.rpc_proxy import ask_dict
result = ask_dict(**args)
print(json.dumps(result))
`;
        const proc = spawn("python", ["-c", script], { cwd: "C:\\Files\\Models\\CosySim" });
        let out = "", err = "";
        proc.stdout.on("data", (d: Buffer) => (out += d.toString()));
        proc.stderr.on("data", (d: Buffer) => (err += d.toString()));
        proc.stdin.write(JSON.stringify({ prompt, model: model || "claude-sonnet-4.6", account_name: account_name || "nihilistcod" }));
        proc.stdin.end();
        const timer = setTimeout(() => { proc.kill(); reject(new Error("Copilot timeout")); }, 60000);
        proc.on("close", (code: number) => {
          clearTimeout(timer);
          if (code !== 0) reject(new Error(err || "Python error"));
          else try { resolve(JSON.parse(out)); } catch { resolve({ response: out }); }
        });
      });
      res.json(result);
    } catch (e: any) { res.status(500).json({ error: e.message }); }
  });

  app.post("/api/copilot/thread/create", async (req, res) => {
    try {
      const result = await callPython(
        "engine.integrations.rpc_proxy", "create_thread_dict",
        { account_name: req.body.account_name || "nihilistcod" }
      );
      res.json(result);
    } catch (e: any) { res.status(500).json({ error: e.message }); }
  });

  app.post("/api/copilot/thread/:id/message", async (req, res) => {
    try {
      const { content, model, parent_message_id, account_name } = req.body;
      const result = await callPython(
        "engine.integrations.rpc_proxy", "send_message_dict",
        {
          thread_id: req.params.id,
          content,
          model: model || "claude-sonnet-4.6",
          parent_message_id: parent_message_id || "root",
          account_name: account_name || "nihilistcod",
        }
      );
      res.json(result);
    } catch (e: any) { res.status(500).json({ error: e.message }); }
  });


  app.get("/api/nexus/rules", async (req, res) => {
    try {
      const scope = (req.query.scope as string) || "global";
      const result = await nexusProxy(`/rules?scope=${encodeURIComponent(scope)}`);
      res.json(result);
    } catch { res.json({ rules: [] }); }
  });

  app.post("/api/nexus/qa", async (req, res) => {
    try {
      const result = await nexusProxy("/qa", "POST", req.body);
      res.json(result);
    } catch (e: any) { res.status(500).json({ error: e.message }); }
  });

  app.get("/api/nexus/search", async (req, res) => {
    try {
      const q = (req.query.q as string) || "";
      const result = await nexusProxy(`/search?q=${encodeURIComponent(q)}`);
      res.json(result);
    } catch { res.json({ results: [] }); }
  });

  app.get("/api/nexus/ask", async (req, res) => {
    try {
      const q = req.query.q as string;
      const result = await nexusProxy(`/ask?q=${encodeURIComponent(q)}`);
      res.json(result);
    } catch { res.json({ answer: "" }); }
  });

  // ── Reader Mode proxy ─────────────────────────────────────────────────────
  // Fetches a URL server-side, extracts main article content with Readability.
  // Bypasses CORS and X-Frame-Options entirely.
  app.get("/api/proxy/reader", async (req, res) => {
    const targetUrl = req.query.url as string;
    if (!targetUrl) return res.status(400).json({ error: "url param required" });
    try {
      const response = await fetch(targetUrl, {
        headers: {
          "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
          "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
          "Accept-Language": "en-US,en;q=0.9",
        },
        redirect: "follow",
      });
      const html = await response.text();
      const finalUrl = response.url || targetUrl;

      // Try Readability first (article-quality extraction)
      try {
        const dom = new JSDOM(html, { url: finalUrl });
        const article = new Readability(dom.window.document).parse();
        if (article && article.textContent.length > 200) {
          return res.json({
            title: article.title,
            byline: article.byline,
            html: article.content,
            text: article.textContent.replace(/\s+/g, " ").trim(),
            excerpt: article.excerpt,
            url: finalUrl,
            mode: "readability",
          });
        }
      } catch (_) { /* fall through to cheerio */ }

      // Fallback: cheerio content extraction
      const $ = cheerio.load(html);
      $("script, style, noscript, iframe, nav, footer, .ad, .advertisement, [class*=cookie], [id*=cookie]").remove();
      const title = $("title").text() || $("h1").first().text();
      const content =
        $("article, main, [role=main], .content, .post, .article, .entry-content").first().html() ||
        $("body").html() ||
        "";
      const $c = cheerio.load(content);
      const text = $c("body").text().replace(/\s+/g, " ").trim();
      res.json({ title, html: content, text, url: finalUrl, mode: "cheerio" });
    } catch (e: any) {
      res.status(500).json({ error: e.message });
    }
  });

  // ── Puppeteer browser sessions ─────────────────────────────────────────────
  // POST /api/browser/start  — launch headless/headed Chrome, begin HAR capture
  app.post("/api/browser/start", async (req, res) => {
    const { url, headless = false, account = "default" } = req.body;
    const sid = sessionId();
    try {
      // Persistent profile per account — keeps sessions, cookies, saved passwords
      const profileDir = path.join(CHROME_PROFILES_DIR, account);
      fs.mkdirSync(profileDir, { recursive: true });

      const browser = await puppeteer.launch({
        executablePath: CHROME_PATH,
        headless: headless === true,
        userDataDir: profileDir,
        defaultViewport: headless ? { width: BROWSER_W, height: BROWSER_H } : null,
        args: [
          "--no-sandbox", "--disable-setuid-sandbox",
          "--disable-blink-features=AutomationControlled",  // hide automation
          "--disable-web-security",
          "--disable-features=IsolateOrigins,site-per-process",
          `--window-size=${BROWSER_W},${BROWSER_H}`,
          "--start-maximized",
        ],
        ignoreDefaultArgs: ["--enable-automation"],  // remove "Chrome is being controlled" bar
      });
      const page = await browser.newPage();

      // Mask automation signals so Google/GitHub don't block login
      await page.evaluateOnNewDocument(() => {
        Object.defineProperty(navigator, "webdriver", { get: () => undefined });
        (window as any).chrome = { runtime: {} };
      });

      const harEntries: HarEntry[] = [];
      const requestTimings = new Map<string, number>();

      // CDP-level HAR recording
      const cdp = await page.createCDPSession();
      await cdp.send("Network.enable");

      cdp.on("Network.requestWillBeSent", (params: any) => {
        requestTimings.set(params.requestId, params.timestamp * 1000);
        const req = params.request;
        const urlObj = new URL(req.url);
        harEntries.push({
          startedDateTime: new Date(params.timestamp * 1000).toISOString(),
          time: 0,
          request: {
            method: req.method,
            url: req.url,
            httpVersion: "HTTP/1.1",
            headers: Object.entries(req.headers || {}).map(([name, value]) => ({ name, value: String(value) })),
            cookies: [],
            queryString: Array.from(urlObj.searchParams.entries()).map(([name, value]) => ({ name, value })),
            postData: req.postData ? { mimeType: req.headers["content-type"] || "text/plain", text: req.postData } : undefined,
            headersSize: -1,
            bodySize: req.postData ? req.postData.length : 0,
          },
          response: {
            status: 0, statusText: "", httpVersion: "HTTP/1.1",
            headers: [], cookies: [], content: { size: 0, mimeType: "" },
            redirectURL: "", headersSize: -1, bodySize: -1,
          },
          timings: { send: 0, wait: 0, receive: 0 },
        } as HarEntry);
      });

      cdp.on("Network.responseReceived", (params: any) => {
        const entry = harEntries.slice().reverse().find((e) => e.request.url === params.response.url);
        if (!entry) return;
        const startMs = requestTimings.get(params.requestId) || 0;
        const nowMs = params.timestamp * 1000;
        entry.response = {
          status: params.response.status,
          statusText: params.response.statusText,
          httpVersion: "HTTP/1.1",
          headers: Object.entries(params.response.headers || {}).map(([name, value]) => ({ name, value: String(value) })),
          cookies: [],
          content: { size: params.response.encodedDataLength || 0, mimeType: params.response.mimeType || "" },
          redirectURL: params.response.redirectResponseUrl || "",
          headersSize: -1,
          bodySize: params.response.encodedDataLength || -1,
        };
        entry.time = nowMs - startMs;
        entry.timings = { send: 0, wait: entry.time, receive: 0 };
      });

      if (url) {
        await page.goto(url, { waitUntil: "domcontentloaded", timeout: 20000 }).catch(() => {});
      }
      browserSessions.set(sid, { browser, page, harEntries, requestTimings, started: Date.now(), account });
      res.json({ sessionId: sid, status: "started", url: page.url() });
    } catch (e: any) {
      res.status(500).json({ error: e.message });
    }
  });

  // GET /api/browser/screenshot/:sid  — current page as JPEG base64
  app.get("/api/browser/screenshot/:sid", async (req, res) => {
    const s = browserSessions.get(req.params.sid);
    if (!s) return res.status(404).json({ error: "session not found" });
    try {
      const screenshot = await s.page.screenshot({ type: "jpeg", quality: 70, encoding: "base64" });
      res.json({ screenshot, url: s.page.url(), title: await s.page.title() });
    } catch (e: any) { res.status(500).json({ error: e.message }); }
  });

  // GET /api/browser/stream/:sid  — SSE screenshot stream (~300ms interval)
  app.get("/api/browser/stream/:sid", (req, res) => {
    res.setHeader("Content-Type", "text/event-stream");
    res.setHeader("Cache-Control", "no-cache");
    res.setHeader("Connection", "keep-alive");
    res.setHeader("Access-Control-Allow-Origin", "*");
    res.flushHeaders();

    const interval = setInterval(async () => {
      const s = browserSessions.get(req.params.sid);
      if (!s) { clearInterval(interval); res.end(); return; }
      try {
        const screenshot = await s.page.screenshot({ type: "jpeg", quality: 65, encoding: "base64" });
        const data = JSON.stringify({ screenshot, url: s.page.url() });
        res.write(`data: ${data}\n\n`);
      } catch (_) { /* page navigating */ }
    }, 350);

    req.on("close", () => clearInterval(interval));
  });

  // POST /api/browser/navigate/:sid
  app.post("/api/browser/navigate/:sid", async (req, res) => {
    const s = browserSessions.get(req.params.sid);
    if (!s) return res.status(404).json({ error: "session not found" });
    try {
      await s.page.goto(req.body.url, { waitUntil: "domcontentloaded", timeout: 20000 });
      res.json({ ok: true, url: s.page.url() });
    } catch (e: any) { res.status(500).json({ error: e.message }); }
  });

  // POST /api/browser/event/:sid  — forward mouse/keyboard events
  app.post("/api/browser/event/:sid", async (req, res) => {
    const s = browserSessions.get(req.params.sid);
    if (!s) return res.status(404).json({ error: "session not found" });
    const { type, x, y, deltaY, key, text, modifiers } = req.body;
    try {
      if (type === "click")      await s.page.mouse.click(x, y);
      if (type === "dblclick")   await s.page.mouse.click(x, y, { clickCount: 2 });
      if (type === "scroll")     await s.page.mouse.wheel({ deltaY: deltaY || 100 });
      if (type === "move")       await s.page.mouse.move(x, y);
      if (type === "keydown")    await s.page.keyboard.press(key);
      if (type === "type")       await s.page.keyboard.type(text, { delay: 10 });
      if (type === "back")       await s.page.goBack({ waitUntil: "domcontentloaded" }).catch(() => {});
      if (type === "forward")    await s.page.goForward({ waitUntil: "domcontentloaded" }).catch(() => {});
      if (type === "refresh")    await s.page.reload({ waitUntil: "domcontentloaded" }).catch(() => {});
      res.json({ ok: true });
    } catch (e: any) { res.status(500).json({ error: e.message }); }
  });

  // GET /api/browser/cookies/:sid  — all current cookies
  app.get("/api/browser/cookies/:sid", async (req, res) => {
    const s = browserSessions.get(req.params.sid);
    if (!s) return res.status(404).json({ error: "session not found" });
    try {
      const cookies = await s.page.cookies();
      res.json({ cookies, count: cookies.length });
    } catch (e: any) { res.status(500).json({ error: e.message }); }
  });

  // POST /api/browser/save-session/:sid  — extract cookies → account pool
  app.post("/api/browser/save-session/:sid", async (req, res) => {
    const s = browserSessions.get(req.params.sid);
    if (!s) return res.status(404).json({ error: "session not found" });
    const account = req.body.account || s.account;
    try {
      const cookies = await s.page.cookies();
      // Group cookies by domain → write to data/accounts/{account}_cookies.json
      const cookieMap: Record<string, Record<string, string>> = {};
      for (const c of cookies) {
        const domain = c.domain.replace(/^\./, "");
        if (!cookieMap[domain]) cookieMap[domain] = {};
        cookieMap[domain][c.name] = c.value;
      }
      const accountsDir = path.join("C:\\Files\\Models\\CosySim", "data", "accounts");
      fs.mkdirSync(accountsDir, { recursive: true });
      const outPath = path.join(accountsDir, `${account}_cookies.json`);

      // Merge with existing file
      let existing: Record<string, Record<string, string>> = {};
      if (fs.existsSync(outPath)) {
        try { existing = JSON.parse(fs.readFileSync(outPath, "utf-8")); } catch (_) {}
      }
      for (const [domain, cooks] of Object.entries(cookieMap)) {
        existing[domain] = { ...(existing[domain] || {}), ...cooks };
      }
      fs.writeFileSync(outPath, JSON.stringify(existing, null, 2));
      res.json({ ok: true, file: outPath, domains: Object.keys(existing), cookies: cookies.length });
    } catch (e: any) { res.status(500).json({ error: e.message }); }
  });

  // GET /api/browser/export-har/:sid  — save recorded traffic as .har file
  app.get("/api/browser/export-har/:sid", async (req, res) => {
    const s = browserSessions.get(req.params.sid);
    if (!s) return res.status(404).json({ error: "session not found" });
    const account = (req.query.account as string) || s.account;
    try {
      const har = {
        log: {
          version: "1.2",
          creator: { name: "CosySim Canvas Browser", version: "0.81" },
          entries: s.harEntries,
        },
      };
      const harDir = `C:\\Files\\Models\\HAR_Files\\${account}`;
      fs.mkdirSync(harDir, { recursive: true });
      const timestamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
      const domain = s.page.url().replace(/https?:\/\/([^/]+).*/, "$1").replace(/[^a-z0-9.-]/gi, "_");
      const filename = `canvas-${domain}-${timestamp}.har`;
      const filepath = path.join(harDir, filename);
      fs.writeFileSync(filepath, JSON.stringify(har));
      res.json({ ok: true, filename, filepath, entries: s.harEntries.length });
    } catch (e: any) { res.status(500).json({ error: e.message }); }
  });

  // GET /api/browser/sessions  — list active sessions
  app.get("/api/browser/sessions", (req, res) => {
    const list = Array.from(browserSessions.entries()).map(([id, s]) => ({
      id,
      account: s.account,
      started: s.started,
      harEntries: s.harEntries.length,
      url: s.page.url().slice(0, 80),
    }));
    res.json({ sessions: list });
  });

  // POST /api/browser/close/:sid
  app.post("/api/browser/close/:sid", async (req, res) => {
    const s = browserSessions.get(req.params.sid);
    if (!s) return res.status(404).json({ error: "session not found" });
    try {
      await s.browser.close();
      browserSessions.delete(req.params.sid);
      res.json({ ok: true });
    } catch (e: any) { res.status(500).json({ error: e.message }); }
  });

  // POST /api/browser/connect-existing — connect to the user's already-running Chrome
  // Chrome must be started with: --remote-debugging-port=9222
  // e.g.  chrome.exe --remote-debugging-port=9222 --no-first-run
  // This does NOT launch a new Chrome — it connects to the authenticated session.
  app.post("/api/browser/connect-existing", async (req, res) => {
    const { debug_port = 9222, url = "", account = "user" } = req.body;
    const sid = sessionId();
    try {
      const browser = await puppeteer.connect({
        browserURL: `http://localhost:${debug_port}`,
        defaultViewport: null,
      });
      const pages = await browser.pages();
      const page = pages.find(p => p.url() !== "about:blank") || pages[0] || (await browser.newPage());
      if (url) await page.goto(url, { waitUntil: "domcontentloaded" });

      const harEntries: HarEntry[] = [];
      const requestTimings = new Map<string, number>();

      const cdp = await page.createCDPSession();
      await cdp.send("Network.enable");

      cdp.on("Network.requestWillBeSent", (params: any) => {
        requestTimings.set(params.requestId, params.timestamp * 1000);
        const r = params.request;
        const urlObj = new URL(r.url);
        harEntries.push({
          startedDateTime: new Date(params.timestamp * 1000).toISOString(),
          time: 0,
          request: {
            method: r.method, url: r.url, httpVersion: "HTTP/1.1",
            headers: Object.entries(r.headers || {}).map(([name, value]) => ({ name, value: String(value) })),
            cookies: [],
            queryString: Array.from(urlObj.searchParams.entries()).map(([name, value]) => ({ name, value })),
            postData: r.postData ? { mimeType: r.headers["content-type"] || "text/plain", text: r.postData } : undefined,
            headersSize: -1, bodySize: r.postData ? r.postData.length : 0,
          },
          response: {
            status: 0, statusText: "", httpVersion: "HTTP/1.1",
            headers: [], cookies: [], content: { size: 0, mimeType: "" },
            redirectURL: "", headersSize: -1, bodySize: -1,
          },
          timings: { send: 0, wait: 0, receive: 0 },
        } as HarEntry);
      });

      cdp.on("Network.responseReceived", (params: any) => {
        const entry = harEntries.slice().reverse().find(e => e.request.url === params.response.url);
        if (!entry) return;
        const startMs = requestTimings.get(params.requestId) || 0;
        entry.response = {
          status: params.response.status, statusText: params.response.statusText,
          httpVersion: "HTTP/1.1",
          headers: Object.entries(params.response.headers || {}).map(([name, value]) => ({ name, value: String(value) })),
          cookies: [], content: { size: params.response.encodedDataLength || 0, mimeType: params.response.mimeType || "" },
          redirectURL: params.response.redirectResponseUrl || "",
          headersSize: -1, bodySize: params.response.encodedDataLength || -1,
        };
        entry.time = (params.timestamp * 1000) - startMs;
        entry.timings = { send: 0, wait: entry.time, receive: 0 };
      });

      browserSessions.set(sid, { browser: browser as any, page, harEntries, requestTimings, account, started: Date.now() });
      res.json({
        sid, ok: true, connected: true, debug_port,
        url: page.url().slice(0, 120),
        message: `Connected to existing Chrome on port ${debug_port}`,
      });
    } catch (e: any) {
      res.status(500).json({
        error: e.message,
        hint: `Make sure Chrome is running with --remote-debugging-port=${debug_port}`,
      });
    }
  });

  // GET /api/browser/chrome-status — check if Chrome remote debug is available
  app.get("/api/browser/chrome-status", async (req, res) => {
    const port = parseInt((req.query.port as string) || "9222", 10);
    try {
      const r = await fetch(`http://localhost:${port}/json/version`, { signal: AbortSignal.timeout(2000) });
      const info = await r.json();
      res.json({ available: true, port, browser: info.Browser, protocol: info.webSocketDebuggerUrl ? "ws" : "http" });
    } catch {
      res.json({ available: false, port, hint: "Start Chrome with: --remote-debugging-port=" + port });
    }
  });

  // ── Python bridge helpers ──────────────────────────────────────────────────
  async function callPython(module: string, method: string, args: Record<string, any>): Promise<any> {
    const { spawn } = await import("child_process");
    const script = `
import json, sys
sys.path.insert(0, r'C:\\Files\\Models\\CosySim')
args = json.loads(sys.stdin.read())
from ${module} import ${method}
result = ${method}(**args)
print(json.dumps(result) if result is not None else json.dumps(None))
`;
    return new Promise((resolve, reject) => {
      const proc = spawn("python", ["-c", script], { cwd: "C:\\Files\\Models\\CosySim" });
      let out = "", err = "";
      proc.stdout.on("data", (d: Buffer) => (out += d.toString()));
      proc.stderr.on("data", (d: Buffer) => (err += d.toString()));
      proc.stdin.write(JSON.stringify(args));
      proc.stdin.end();
      const timer = setTimeout(() => { proc.kill(); reject(new Error("Python timeout")); }, 30000);
      proc.on("close", (code: number) => {
        clearTimeout(timer);
        if (code !== 0) reject(new Error(err || "Python error"));
        else try { resolve(JSON.parse(out)); } catch { resolve(out); }
      });
    });
  }

  async function nexusProxy(nexusPath: string, method = "GET", body?: any): Promise<any> {
    const resp = await fetch(`http://localhost:8700/api${nexusPath}`, {
      method,
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    });
    return resp.json();
  }

  // Vite middleware for development
  if (process.env.NODE_ENV !== "production") {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: "spa",
    });
    app.use(vite.middlewares);
  } else {
    app.use(express.static("dist"));
  }

  app.listen(PORT, "0.0.0.0", () => {
    console.log(`Server running on http://localhost:${PORT}`);
  });
}

startServer();
