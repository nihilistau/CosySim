import React, { useState, useRef, useEffect, useCallback } from "react";
import {
  Globe, RefreshCw, Plus, Copy, FileText, ChevronUp, ChevronDown,
  Monitor, BookOpen, ArrowLeft, ArrowRight,
  WifiOff, Loader2, AlertCircle, Wifi, Key,
} from "lucide-react";
import TurndownService from "turndown";

type BrowserMode = "iframe" | "reader" | "live";

interface Props {
  onAddSource: (title: string, content: string, type: "text" | "url" | "file", url?: string) => void;
}

interface LiveSession {
  sessionId: string;
  account: string;
  currentUrl: string;
  harEntries: number;
}

export default function Browser({ onAddSource }: Props) {
  const [mode, setMode] = useState<BrowserMode>("reader");
  const [inputUrl, setInputUrl] = useState("https://en.wikipedia.org/wiki/Main_Page");
  const [isCollapsed, setIsCollapsed] = useState(false);

  // Reader mode
  const [readerContent, setReaderContent] = useState<{ title: string; html: string; url: string } | null>(null);
  const [isLoadingReader, setIsLoadingReader] = useState(false);
  const [readerError, setReaderError] = useState<string | null>(null);

  // Live (Puppeteer) mode
  const [liveSession, setLiveSession] = useState<LiveSession | null>(null);
  const [screenshot, setScreenshot] = useState<string | null>(null);
  const [isStartingSession, setIsStartingSession] = useState(false);
  const [liveError, setLiveError] = useState<string | null>(null);
  const [accountName, setAccountName] = useState("default");
  const [isHeadless, setIsHeadless] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [saveResult, setSaveResult] = useState<string | null>(null);

  const imgRef = useRef<HTMLImageElement>(null);
  const sseRef = useRef<EventSource | null>(null);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const turndown = new TurndownService();

  // ── SSE screenshot stream ──────────────────────────────────────────────────
  const startScreenshotStream = useCallback((sid: string) => {
    sseRef.current?.close();
    const es = new EventSource(`/api/browser/stream/${sid}`);
    es.onmessage = (e) => {
      const data = JSON.parse(e.data);
      setScreenshot(data.screenshot);
      if (data.url) {
        setLiveSession((prev) => prev ? { ...prev, currentUrl: data.url } : prev);
      }
    };
    es.onerror = () => { setLiveError("Stream disconnected"); es.close(); };
    sseRef.current = es;
  }, []);

  // ── Start Puppeteer session ────────────────────────────────────────────────
  const handleStartLive = async () => {
    setIsStartingSession(true);
    setLiveError(null);
    try {
      const url = inputUrl.startsWith("http") ? inputUrl : `https://${inputUrl}`;
      const r = await fetch("/api/browser/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, headless: isHeadless, account: accountName }),
      });
      const data = await r.json();
      if (data.error) throw new Error(data.error);
      setLiveSession({ sessionId: data.sessionId, account: accountName, currentUrl: data.url, harEntries: 0 });
      startScreenshotStream(data.sessionId);
    } catch (e: any) {
      setLiveError(e.message);
    } finally {
      setIsStartingSession(false);
    }
  };

  // ── Close Puppeteer session ────────────────────────────────────────────────
  const handleCloseLive = async () => {
    if (!liveSession) return;
    sseRef.current?.close();
    sseRef.current = null;
    await fetch(`/api/browser/close/${liveSession.sessionId}`, { method: "POST" }).catch(() => {});
    setLiveSession(null);
    setScreenshot(null);
  };

  // ── Navigate live browser ──────────────────────────────────────────────────
  const handleLiveNavigate = async (url?: string) => {
    if (!liveSession) return;
    const target = url || (inputUrl.startsWith("http") ? inputUrl : `https://${inputUrl}`);
    await fetch(`/api/browser/navigate/${liveSession.sessionId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: target }),
    });
  };

  const sendBrowserEvent = (payload: object) => {
    if (!liveSession) return;
    fetch(`/api/browser/event/${liveSession.sessionId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  };

  // ── Forward mouse click ────────────────────────────────────────────────────
  const handleScreenshotClick = useCallback((e: React.MouseEvent<HTMLImageElement>) => {
    if (!liveSession || !imgRef.current) return;
    const rect = imgRef.current.getBoundingClientRect();
    sendBrowserEvent({ type: "click", x: (e.clientX - rect.left) * (1280 / rect.width), y: (e.clientY - rect.top) * (800 / rect.height) });
  }, [liveSession]);

  const handleScreenshotWheel = useCallback((e: React.WheelEvent) => {
    if (!liveSession) return;
    sendBrowserEvent({ type: "scroll", deltaY: e.deltaY });
  }, [liveSession]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (!liveSession) return;
    e.preventDefault();
    sendBrowserEvent({ type: "keydown", key: e.key });
  }, [liveSession]);

  // ── Save session (cookies + HAR) ──────────────────────────────────────────
  const handleSaveSession = async () => {
    if (!liveSession) return;
    setIsSaving(true);
    setSaveResult(null);
    try {
      const [cookieRes, harRes] = await Promise.all([
        fetch(`/api/browser/save-session/${liveSession.sessionId}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ account: liveSession.account }),
        }).then((r) => r.json()),
        fetch(`/api/browser/export-har/${liveSession.sessionId}?account=${liveSession.account}`).then((r) => r.json()),
      ]);
      setSaveResult(`✓ ${cookieRes.domains?.length || 0} domains, ${harRes.entries || 0} HAR entries → ${liveSession.account}`);
      setLiveSession((prev) => prev ? { ...prev, harEntries: harRes.entries || 0 } : prev);
    } catch (e: any) {
      setSaveResult(`✗ ${e.message}`);
    } finally {
      setIsSaving(false);
      setTimeout(() => setSaveResult(null), 5000);
    }
  };

  // ── Reader mode load ───────────────────────────────────────────────────────
  const handleLoadReader = async (url?: string) => {
    const target = url || (inputUrl.startsWith("http") ? inputUrl : `https://${inputUrl}`);
    setIsLoadingReader(true);
    setReaderError(null);
    try {
      const r = await fetch(`/api/proxy/reader?url=${encodeURIComponent(target)}`);
      const data = await r.json();
      if (data.error) throw new Error(data.error);
      setReaderContent({ title: data.title || target, html: data.html || "", url: target });
    } catch (e: any) {
      setReaderError(e.message);
    } finally {
      setIsLoadingReader(false);
    }
  };

  const handleGo = (e: React.FormEvent) => {
    e.preventDefault();
    if (mode === "reader") handleLoadReader();
    if (mode === "live") liveSession ? handleLiveNavigate() : handleStartLive();
  };

  useEffect(() => () => sseRef.current?.close(), []);

  const modeBtn = (m: BrowserMode, icon: React.ReactNode, label: string) => (
    <button
      onClick={() => setMode(m)}
      className={`flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium transition-colors ${mode === m ? "bg-blue-600 text-white" : "text-zinc-500 hover:bg-zinc-200 dark:hover:bg-zinc-700"}`}
    >
      {icon} {label}
    </button>
  );

  return (
    <div className={`flex flex-col border-b border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 transition-all duration-300 ${isCollapsed ? "h-10" : "h-2/5 min-h-[300px]"}`}>

      {/* ── Toolbar ── */}
      <div className="flex items-center p-1.5 border-b border-zinc-200 dark:border-zinc-800 gap-1.5 bg-zinc-50 dark:bg-zinc-950 h-10 shrink-0">
        <button onClick={() => setIsCollapsed(!isCollapsed)} className="p-1 hover:bg-zinc-200 dark:hover:bg-zinc-800 rounded text-zinc-500 shrink-0">
          {isCollapsed ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronUp className="w-3.5 h-3.5" />}
        </button>

        <div className="flex gap-0.5 shrink-0">
          {modeBtn("iframe", <Globe className="w-3 h-3" />, "Iframe")}
          {modeBtn("reader", <BookOpen className="w-3 h-3" />, "Reader")}
          {modeBtn("live", <Monitor className="w-3 h-3" />, "Live")}
        </div>

        <div className="w-px h-5 bg-zinc-300 dark:bg-zinc-700 shrink-0" />

        <form onSubmit={handleGo} className="flex-1 flex min-w-0">
          <input
            type="text"
            value={inputUrl}
            onChange={(e) => setInputUrl(e.target.value)}
            className="flex-1 bg-white dark:bg-zinc-900 border border-zinc-300 dark:border-zinc-700 rounded px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-blue-500 text-zinc-900 dark:text-zinc-100 min-w-0"
            placeholder="Enter URL…"
          />
        </form>

        <button onClick={() => mode === "reader" ? handleLoadReader() : mode === "live" && liveSession ? handleLiveNavigate() : undefined}
          className="p-1 hover:bg-zinc-200 dark:hover:bg-zinc-800 rounded text-zinc-500 shrink-0">
          <RefreshCw className="w-3.5 h-3.5" />
        </button>

        {/* Reader extras */}
        {mode === "reader" && readerContent && (
          <>
            <button onClick={() => onAddSource(readerContent.title, readerContent.url, "url", readerContent.url)} title="Add URL as Source" className="p-1 hover:bg-zinc-200 dark:hover:bg-zinc-800 rounded text-zinc-500 shrink-0"><Plus className="w-3.5 h-3.5" /></button>
            <button onClick={() => onAddSource(readerContent.title, turndown.turndown(readerContent.html), "text", readerContent.url)} title="Convert to Markdown Source" className="p-1 hover:bg-zinc-200 dark:hover:bg-zinc-800 rounded text-zinc-500 shrink-0"><FileText className="w-3.5 h-3.5" /></button>
          </>
        )}

        {/* Live extras */}
        {mode === "live" && (
          <div className="flex items-center gap-1 shrink-0">
            <input value={accountName} onChange={(e) => setAccountName(e.target.value)} placeholder="account"
              className="w-20 bg-white dark:bg-zinc-900 border border-zinc-300 dark:border-zinc-700 rounded px-1.5 py-0.5 text-xs focus:outline-none" />
            {liveSession ? (
              <>
                <button onClick={() => sendBrowserEvent({ type: "back" })} title="Back" className="p-1 hover:bg-zinc-200 dark:hover:bg-zinc-800 rounded text-zinc-500"><ArrowLeft className="w-3.5 h-3.5" /></button>
                <button onClick={() => sendBrowserEvent({ type: "forward" })} title="Forward" className="p-1 hover:bg-zinc-200 dark:hover:bg-zinc-800 rounded text-zinc-500"><ArrowRight className="w-3.5 h-3.5" /></button>
                <button onClick={handleSaveSession} disabled={isSaving} title="Capture: save cookies + export HAR"
                  className="flex items-center gap-1 px-2 py-0.5 bg-emerald-600 hover:bg-emerald-700 text-white text-xs rounded font-medium disabled:opacity-50">
                  {isSaving ? <Loader2 className="w-3 h-3 animate-spin" /> : <Key className="w-3 h-3" />} Capture
                </button>
                <span className="text-xs text-zinc-400">{liveSession.harEntries} req</span>
                <Wifi className="w-3.5 h-3.5 text-emerald-500" />
                <button onClick={handleCloseLive} title="Close Browser" className="p-1 hover:bg-red-100 dark:hover:bg-red-900 text-red-500 rounded"><WifiOff className="w-3.5 h-3.5" /></button>
              </>
            ) : (
              <button onClick={handleStartLive} disabled={isStartingSession}
                className="flex items-center gap-1 px-2 py-0.5 bg-blue-600 hover:bg-blue-700 text-white text-xs rounded font-medium disabled:opacity-50">
                {isStartingSession ? <Loader2 className="w-3 h-3 animate-spin" /> : <Monitor className="w-3 h-3" />}
                {isStartingSession ? "Launching…" : "Launch"}
              </button>
            )}
          </div>
        )}

        {mode === "iframe" && (
          <button onClick={() => navigator.clipboard.writeText(inputUrl)} title="Copy URL" className="p-1 hover:bg-zinc-200 dark:hover:bg-zinc-800 rounded text-zinc-500 shrink-0">
            <Copy className="w-3.5 h-3.5" />
          </button>
        )}
      </div>

      {/* Save result toast */}
      {saveResult && (
        <div className={`px-3 py-1 text-xs font-medium shrink-0 ${saveResult.startsWith("✓") ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200" : "bg-red-100 text-red-800"}`}>
          {saveResult}
        </div>
      )}

      {/* ── Content area ── */}
      {!isCollapsed && (
        <div className="flex-1 relative overflow-hidden bg-white dark:bg-zinc-900">

          {/* IFRAME */}
          {mode === "iframe" && (
            <iframe ref={iframeRef} src={inputUrl} className="w-full h-full border-none"
              sandbox="allow-same-origin allow-scripts allow-popups allow-forms" />
          )}

          {/* READER */}
          {mode === "reader" && (
            <div className="w-full h-full overflow-y-auto p-4">
              {isLoadingReader && (
                <div className="flex items-center justify-center h-32 gap-2 text-zinc-400">
                  <Loader2 className="w-5 h-5 animate-spin" /><span className="text-sm">Fetching…</span>
                </div>
              )}
              {readerError && <div className="flex items-center gap-2 text-red-500 text-sm"><AlertCircle className="w-4 h-4" />{readerError}</div>}
              {!isLoadingReader && !readerContent && !readerError && (
                <div className="flex flex-col items-center justify-center h-full gap-3 text-zinc-400 pt-8">
                  <BookOpen className="w-10 h-10 opacity-30" />
                  <p className="text-sm">Enter a URL and press Enter — extracts clean article content, bypasses CORS &amp; X-Frame-Options.</p>
                  <button onClick={() => handleLoadReader()} className="px-4 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700">
                    Load {inputUrl.slice(0, 50)}
                  </button>
                </div>
              )}
              {readerContent && !isLoadingReader && (
                <div className="max-w-3xl mx-auto">
                  <h1 className="text-xl font-bold text-zinc-900 dark:text-zinc-100 mb-1">{readerContent.title}</h1>
                  <p className="text-xs text-zinc-400 mb-4">{readerContent.url}</p>
                  <div className="prose prose-sm dark:prose-invert max-w-none text-zinc-800 dark:text-zinc-200"
                    dangerouslySetInnerHTML={{ __html: readerContent.html }} />
                </div>
              )}
            </div>
          )}

          {/* LIVE */}
          {mode === "live" && (
            <div className="w-full h-full flex flex-col">
              {!liveSession ? (
                <div className="flex flex-col items-center justify-center h-full gap-3 text-zinc-400">
                  <Monitor className="w-10 h-10 opacity-30" />
                  <p className="text-sm font-medium">Live Browser — Real Chrome via Puppeteer</p>
                  <p className="text-xs text-center max-w-xs text-zinc-500">All network traffic captured as HAR. Press <strong>Capture</strong> to save cookies + HAR for token refresh.</p>
                  <div className="flex items-center gap-3 text-xs">
                    <label className="flex items-center gap-1 cursor-pointer">
                      <input type="checkbox" checked={isHeadless} onChange={(e) => setIsHeadless(e.target.checked)} className="w-3 h-3" />
                      Headless
                    </label>
                    <span>Account: <input value={accountName} onChange={(e) => setAccountName(e.target.value)} className="w-24 border border-zinc-300 dark:border-zinc-600 rounded px-1.5 py-0.5 bg-white dark:bg-zinc-800 text-xs ml-1" /></span>
                  </div>
                  {liveError && <div className="flex items-center gap-2 text-red-500 text-xs"><AlertCircle className="w-3.5 h-3.5" />{liveError}</div>}
                  <button onClick={handleStartLive} disabled={isStartingSession}
                    className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50">
                    {isStartingSession ? <Loader2 className="w-4 h-4 animate-spin" /> : <Monitor className="w-4 h-4" />}
                    {isStartingSession ? "Launching Chrome…" : "Launch Browser"}
                  </button>
                </div>
              ) : (
                <div className="flex-1 relative overflow-hidden" tabIndex={0} onKeyDown={handleKeyDown}>
                  {screenshot ? (
                    <img
                      ref={imgRef}
                      src={`data:image/jpeg;base64,${screenshot}`}
                      alt="Live browser"
                      className="w-full h-full object-contain cursor-pointer select-none"
                      onClick={handleScreenshotClick}
                      onWheel={handleScreenshotWheel}
                      draggable={false}
                    />
                  ) : (
                    <div className="flex items-center justify-center h-full gap-2 text-zinc-400">
                      <Loader2 className="w-5 h-5 animate-spin" /><span className="text-sm">Loading screenshot…</span>
                    </div>
                  )}
                  <div className="absolute bottom-0 left-0 right-0 bg-black/60 text-white text-xs px-2 py-1 truncate pointer-events-none">
                    {liveSession.currentUrl}
                  </div>
                </div>
              )}
            </div>
          )}

        </div>
      )}
    </div>
  );
}
