import express from "express";
import { createServer as createViteServer } from "vite";
import { db } from "./src/db.js";
import * as cheerio from "cheerio";

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
    const result = await proxyToSidecar("/api/nexus/search", req.body);
    if (result.error) {
      res.status(503).json({ error: "Service unavailable", detail: result.error });
    } else {
      res.status(result.status).json(result.data);
    }
  });

  app.post("/api/nexus/ask", async (req, res) => {
    const result = await proxyToSidecar("/api/nexus/ask", req.body);
    if (result.error) {
      res.status(503).json({ error: "Service unavailable", detail: result.error });
    } else {
      res.status(result.status).json(result.data);
    }
  });

  app.post("/api/nexus/add", async (req, res) => {
    const result = await proxyToSidecar("/api/nexus/add", req.body);
    if (result.error) {
      res.status(503).json({ error: "Service unavailable", detail: result.error });
    } else {
      res.status(result.status).json(result.data);
    }
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
