import express from "express";
import { createServer as createViteServer } from "vite";
import { db } from "./src/db.js";
import * as cheerio from "cheerio";
import * as fs from "fs";
import * as path from "path";

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
    const result = await proxyToSidecar("/api/accounts");
    if (result.error) {
      res.status(503).json({ error: "Service unavailable", detail: result.error });
    } else {
      res.status(result.status).json(result.data);
    }
  });

  app.post("/api/accounts/import-har", async (req, res) => {
    const result = await proxyToSidecar("/api/accounts/import-har", req.body);
    if (result.error) {
      res.status(503).json({ error: "Service unavailable", detail: result.error });
    } else {
      res.status(result.status).json(result.data);
    }
  });

  app.post("/api/accounts/import-directory", async (req, res) => {
    const result = await proxyToSidecar("/api/accounts/import-directory", req.body);
    if (result.error) {
      res.status(503).json({ error: "Service unavailable", detail: result.error });
    } else {
      res.status(result.status).json(result.data);
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
    try {
      const r = await fetch(`${NEXUS_API}/api/nlm/notebooks`);
      const data = await r.json();
      res.json(data);
    } catch {
      res.json({ notebooks: [], error: "Nexus KMS not available" });
    }
  });

  app.post("/api/nlm/ask", async (req, res) => {
    try {
      const r = await fetch(`${NEXUS_API}/api/nlm/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(req.body),
      });
      const data = await r.json();
      res.status(r.status).json(data);
    } catch (e: any) {
      res.status(503).json({ error: "Nexus KMS not available", detail: e.message });
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

  const HAR_DIR = "C:\\Files\\Models\\CosySim\\data\\har_files";

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
    return walk(HAR_DIR);
  }

  // ── HAR File Management ───────────────────────────────────────────────────
  app.get("/api/har/list", async (req, res) => {
    try {
      const entries: { name: string; path: string; size: number; domain: string }[] = [];
      function walk(dir: string): void {
        if (!fs.existsSync(dir)) return;
        for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
          const full = path.join(dir, entry.name);
          if (entry.isDirectory()) walk(full);
          else if (entry.name.endsWith(".har")) {
            const stat = fs.statSync(full);
            const domain = entry.name.replace(/\.har$/, "").replace(/_\d+$/, "");
            entries.push({ name: entry.name, path: full, size: stat.size, domain });
          }
        }
      }
      walk(HAR_DIR);
      res.json(entries);
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
      const { filepath, account_name, services } = req.body;
      const result = await callPython(
        "engine.integrations.rpc_proxy", "import_har_to_pool",
        { filepath, account_name, services }
      );
      res.json(result);
    } catch (e: any) { res.status(500).json({ error: e.message }); }
  });

  app.get("/api/har/:filename/entries", async (req, res) => {
    try {
      const harPath = findHarFile(req.params.filename);
      if (!harPath) return res.status(404).json({ error: "HAR file not found" });
      const filter = (req.query.filter as string) || "";
      const methodFilter = (req.query.method as string) || "";
      const limit = parseInt(req.query.limit as string) || 100;
      const offset = parseInt(req.query.offset as string) || 0;
      const raw = JSON.parse(fs.readFileSync(harPath, "utf-8"));
      let entries: any[] = raw.log?.entries || [];
      if (filter) entries = entries.filter((e: any) => e.request?.url?.includes(filter));
      if (methodFilter) entries = entries.filter((e: any) => e.request?.method === methodFilter.toUpperCase());
      const total = entries.length;
      const page = entries.slice(offset, offset + limit).map((e: any, i: number) => ({
        idx: offset + i,
        method: e.request?.method,
        url: e.request?.url,
        status: e.response?.status,
        size: e.response?.content?.size || 0,
        timing: e.time,
      }));
      res.json({ total, entries: page });
    } catch (e: any) { res.status(500).json({ error: e.message }); }
  });

  app.get("/api/har/:filename/entry/:idx", async (req, res) => {
    try {
      const harPath = findHarFile(req.params.filename);
      if (!harPath) return res.status(404).json({ error: "HAR file not found" });
      const raw = JSON.parse(fs.readFileSync(harPath, "utf-8"));
      const entry = (raw.log?.entries || [])[parseInt(req.params.idx)];
      if (!entry) return res.status(404).json({ error: "Entry not found" });
      res.json(entry);
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

  // ── Nexus rules + QA (GET variants) ───────────────────────────────────────
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
