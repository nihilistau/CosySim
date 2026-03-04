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

  // ── LMStudio direct integration ───────────────────────────────────────────
  const LM_STUDIO_URL = process.env.LOCAL_LM_STUDIO_URL || "http://localhost:1234";
  const INTERNAL_API_KEY = process.env.INTERNAL_API_KEY || "cosysim-canvas-internal";

  // GET /api/lmstudio/health — check if LMStudio is reachable
  app.get("/api/lmstudio/health", async (_req, res) => {
    try {
      const r = await fetch(`${LM_STUDIO_URL}/api/v1/models`, {
        signal: AbortSignal.timeout(3000),
      });
      const data = await r.json();
      const models = (data.data || []).map((m: any) => m.id);
      res.json({ status: "ok", url: LM_STUDIO_URL, models });
    } catch (e: any) {
      res.status(503).json({ status: "offline", error: e.message });
    }
  });

  // GET /api/lmstudio/models
  app.get("/api/lmstudio/models", async (_req, res) => {
    try {
      const r = await fetch(`${LM_STUDIO_URL}/api/v1/models`);
      const data = await r.json();
      const raw: any[] = data.data || data.models || [];
      // Normalize: LMStudio v1 uses 'key' not 'id'; map key→id; filter to LLM type only
      const models = raw
        .filter((m: any) => !m.type || m.type === 'llm')
        .map((m: any) => ({ ...m, id: m.id || m.key }));
      res.json({ models });
    } catch (e: any) {
      res.status(503).json({ error: `LMStudio unreachable: ${e.message}` });
    }
  });

  // POST /api/lmstudio/chat — non-streaming chat completions via LMStudio native /api/v1/chat
  app.post("/api/lmstudio/chat", async (req, res) => {
    const {
      messages = [],
      model = "",
      temperature = 0.7,
      max_tokens = 1024,
      stream = false,
      system = "",
    } = req.body;

    // Convert OpenAI-style messages to LMStudio native v1 input format
    const systemParts: string[] = [];
    const inputItems: any[] = [];
    for (const msg of messages) {
      if (msg.role === "system") { systemParts.push(msg.content); continue; }
      const prefix = msg.role === "assistant" ? "[assistant]: " : "";
      inputItems.push({ type: "text", content: prefix + (msg.content ?? "") });
    }
    if (system) systemParts.unshift(system);
    // Simplify: single item → plain string
    const input = inputItems.length === 1 ? inputItems[0].content : inputItems.length === 0 ? "" : inputItems;

    const body = JSON.stringify({
      model: model || undefined,
      input,
      ...(systemParts.length ? { system_prompt: systemParts.join("\n\n") } : {}),
      temperature,
      max_output_tokens: max_tokens,
      stream,
    });

    try {
      const r = await fetch(`${LM_STUDIO_URL}/api/v1/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
      });

      if (stream) {
        res.setHeader("Content-Type", "text/event-stream");
        res.setHeader("Cache-Control", "no-cache");
        res.setHeader("Connection", "keep-alive");
        const reader = r.body?.getReader();
        const decoder = new TextDecoder();
        if (reader) {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            res.write(decoder.decode(value, { stream: true }));
          }
        }
        res.end();
      } else {
        const data = await r.json();
        // Native v1 response: { output: [{type:"text"|"message",content/text:"..."}, ...], stats, response_id }
        let text = "";
        if (Array.isArray(data.output)) {
          const textItem = data.output.find((o: any) => o.type === "text" || o.type === "message");
          text = textItem?.content ?? textItem?.text ?? "";
          if (!text) {
            const reasoning = data.output.find((o: any) => o.type === "reasoning");
            text = reasoning?.content ?? reasoning?.text ?? "";
          }
        }
        // Fallback: choices shape or flat content
        if (!text) text = data.choices?.[0]?.message?.content || data.content || "";
        res.json({ text, model: data.model_instance_id ?? data.model ?? model, response_id: data.response_id, usage: data.stats });
      }
    } catch (e: any) {
      res.status(503).json({ error: `LMStudio unavailable: ${e.message}` });
    }
  });

  // POST /api/lmstudio/load — load a model
  app.post("/api/lmstudio/load", async (req, res) => {
    try {
      const r = await fetch(`${LM_STUDIO_URL}/api/v1/models/load`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(req.body),
      });
      res.status(r.status).json(await r.json().catch(() => ({})));
    } catch (e: any) {
      res.status(503).json({ error: e.message });
    }
  });

  // POST /api/lmstudio/download — download a model
  app.post("/api/lmstudio/download", async (req, res) => {
    try {
      const r = await fetch(`${LM_STUDIO_URL}/api/v1/models/download`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(req.body),
      });
      res.status(r.status).json(await r.json().catch(() => ({})));
    } catch (e: any) {
      res.status(503).json({ error: e.message });
    }
  });

  // GET /api/lmstudio/download/status/:jobId
  app.get("/api/lmstudio/download/status/:jobId", async (req, res) => {
    try {
      const r = await fetch(`${LM_STUDIO_URL}/api/v1/models/download/status/${req.params.jobId}`);
      res.status(r.status).json(await r.json().catch(() => ({})));
    } catch (e: any) {
      res.status(503).json({ error: e.message });
    }
  });

  // POST /api/external/ingest — push a node from any external client (Python, scripts, agents)
  // Protected by x-api-key header matching INTERNAL_API_KEY.
  // Stores the node as a source in the default/first notebook, or creates one.
  app.post("/api/external/ingest", async (req, res) => {
    const key = req.headers["x-api-key"];
    if (key !== INTERNAL_API_KEY) {
      return res.status(401).json({ error: "Unauthorized — x-api-key mismatch" });
    }
    const { content, source = "external", type = "note", notebook_id = "" } = req.body;
    if (!content) return res.status(400).json({ error: "content required" });

    const nodeId = `node_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
    const ts = new Date().toISOString();

    // Resolve target notebook: use provided id, or first notebook, or create one
    let nbId = notebook_id as string;
    if (!nbId) {
      const nb = db.prepare("SELECT id FROM notebooks ORDER BY created_at LIMIT 1").get() as any;
      if (nb) {
        nbId = nb.id;
      } else {
        nbId = `nb_${Date.now()}`;
        db.prepare("INSERT INTO notebooks (id, name) VALUES (?, ?)").run(nbId, "Ingest");
      }
    }

    db.prepare(`
      INSERT INTO sources (id, notebook_id, title, content, type, url)
      VALUES (?, ?, ?, ?, ?, ?)
    `).run(nodeId, nbId, `[${source}] ${ts.slice(0, 19)}`, content, type, source);

    res.json({ status: "ok", nodeId, notebook_id: nbId });
  });

  // ── Canvas API proxy (Python backend at 5595) ─────────────────────────────
  const CANVAS_API = process.env.CANVAS_API_URL || "http://localhost:5595";
  const NEXUS_API = "http://localhost:8700";

  // Generic proxy to Canvas API Python backend — forwards request body and query string
  async function proxyToCanvasApi(req: any, res: any): Promise<void> {
    const url = new URL(`${CANVAS_API}${req.path}`);
    Object.entries(req.query as Record<string, string>).forEach(([k, v]) => url.searchParams.set(k, v));
    try {
      const isGet = req.method === "GET" || req.method === "DELETE";
      const r = await fetch(url.toString(), {
        method: req.method,
        headers: { "Content-Type": "application/json" },
        body: isGet ? undefined : JSON.stringify(req.body),
      });
      const data = await r.json().catch(() => ({}));
      res.status(r.status).json(data);
    } catch (e: any) {
      res.status(503).json({ error: `Canvas API unavailable: ${e.message}` });
    }
  }

  // Mount all Python-backed route prefixes as pass-throughs to Canvas API
  const PYTHON_PREFIXES = [
    "/api/accounts",
    "/api/har",
    "/api/training",
    "/api/nexus",
    "/api/nlm",
    "/api/compute",
    "/api/copilot",
    "/api/rpc",
    "/api/sidecar",
  ];
  for (const prefix of PYTHON_PREFIXES) {
    app.all(`${prefix}`, proxyToCanvasApi);
    app.all(`${prefix}/*`, proxyToCanvasApi);
  }

  // Legacy sidecar constant kept for reference but unused
  const CANVAS_SIDECAR = CANVAS_API;

  // ── AI Studio ─────────────────────────────────────────────────────────────
  const GEMINI_MODELS = [
    { id: "gemini-2.0-flash",                  name: "Gemini 2.0 Flash" },
    { id: "gemini-2.0-flash-thinking-exp-01-21", name: "Gemini 2.0 Flash Thinking" },
    { id: "gemini-2.5-pro-exp-03-25",           name: "Gemini 2.5 Pro (Exp)" },
    { id: "gemini-1.5-pro-latest",              name: "Gemini 1.5 Pro" },
    { id: "gemini-1.5-flash-latest",            name: "Gemini 1.5 Flash" },
    { id: "gemini-1.5-flash-8b",                name: "Gemini 1.5 Flash 8B" },
  ];

  app.post("/api/aistudio/generate", async (req, res) => {
    const apiKey = process.env.GEMINI_API_KEY;
    if (!apiKey) {
      return res.status(401).json({ error: "No GEMINI_API_KEY — set it in environment or use HAR-based auth" });
    }
    try {
      const { model = "gemini-2.0-flash", messages = [], temperature = 0.7, systemPrompt = "" } = req.body;
      const { GoogleGenAI } = await import("@google/genai");
      const genai = new GoogleGenAI({ apiKey });
      const contents = (messages as any[]).map((m: any) => ({
        role: m.role === "assistant" ? "model" : "user",
        parts: [{ text: m.content }],
      }));
      const result = await genai.models.generateContent({
        model,
        contents,
        config: { temperature, systemInstruction: systemPrompt || undefined },
      });
      res.json({ text: result.text, model });
    } catch (e: any) {
      res.status(500).json({ error: e.message });
    }
  });

  app.get("/api/aistudio/models", async (_req, res) => {
    res.json({ models: GEMINI_MODELS });
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
