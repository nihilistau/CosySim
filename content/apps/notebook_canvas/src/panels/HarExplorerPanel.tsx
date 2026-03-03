/**
 * HarExplorerPanel — Browse, filter, analyze and import HAR files.
 *
 * Layout: sidebar (HAR file list) + main (analyze / entry browser + detail).
 */

import React, { useState, useEffect, useRef } from 'react';
import {
  FileText, Upload, RefreshCw, Search, Loader, Copy, Key, Filter,
  AlertCircle, Play, Database, BarChart2, Shield, Github, Globe,
  ChevronDown, ChevronRight,
} from 'lucide-react';
import { HARFile, HAREntry } from '../types';

// ── Helpers ──────────────────────────────────────────────────────────────────

function MethodBadge({ method }: { method: string }) {
  const colors: Record<string, string> = {
    GET: 'bg-blue-100 text-blue-700 dark:bg-blue-900/50 dark:text-blue-300',
    POST: 'bg-green-100 text-green-700 dark:bg-green-900/50 dark:text-green-300',
    PUT: 'bg-amber-100 text-amber-700 dark:bg-amber-900/50 dark:text-amber-300',
    DELETE: 'bg-red-100 text-red-700 dark:bg-red-900/50 dark:text-red-300',
    PATCH: 'bg-purple-100 text-purple-700 dark:bg-purple-900/50 dark:text-purple-300',
  };
  return (
    <span className={`px-1.5 py-0.5 rounded text-[10px] font-mono font-bold uppercase ${colors[method] ?? 'bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400'}`}>
      {method}
    </span>
  );
}

function StatusBadge({ status }: { status: number }) {
  const cls = status >= 500 ? 'text-red-600 dark:text-red-400'
    : status >= 400 ? 'text-amber-600 dark:text-amber-400'
    : status >= 300 ? 'text-blue-600 dark:text-blue-400'
    : 'text-emerald-600 dark:text-emerald-400';
  return <span className={`text-[11px] font-mono font-bold ${cls}`}>{status}</span>;
}

function truncateUrl(url: string, max = 72): string {
  if (url.length <= max) return url;
  return url.slice(0, max - 3) + '…';
}

function stripXSSI(body: string): string {
  for (const prefix of [")]}'\n", ")]}'", ")]}'"]) {
    if (body.startsWith(prefix)) return body.slice(prefix.length);
  }
  return body;
}

function tryFormatJSON(raw: string): string {
  try {
    const cleaned = stripXSSI(raw);
    return JSON.stringify(JSON.parse(cleaned), null, 2);
  } catch {
    return raw;
  }
}

// ── Sidebar: HAR file list ───────────────────────────────────────────────────

function HarSidebar({
  files, selectedFile, onSelect, onRefresh,
}: {
  files: HARFile[];
  selectedFile: HARFile | null;
  onSelect: (f: HARFile) => void;
  onRefresh: () => void;
}) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    const form = new FormData();
    form.append('file', file);
    try {
      // Upload directly to sidecar (server.ts returns 501 for multipart)
      await fetch('http://localhost:5591/api/har/upload', { method: 'POST', body: form });
      onRefresh();
    } finally {
      setUploading(false);
      e.target.value = '';
    }
  };

  const handleImportAccount = async (f: HARFile) => {
    await fetch('/api/har/import-account', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: f.path, account_name: f.name.replace('.har', '') }),
    });
  };

  return (
    <div className="flex flex-col h-full w-52 shrink-0 border-r border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900">
      <div className="flex items-center justify-between px-3 py-2 border-b border-zinc-200 dark:border-zinc-800">
        <h3 className="text-xs font-semibold text-zinc-600 dark:text-zinc-400 uppercase tracking-wider flex items-center gap-1">
          <FileText size={11} /> HAR Files
        </h3>
        <div className="flex gap-1">
          <button onClick={onRefresh} className="p-1 hover:bg-zinc-200 dark:hover:bg-zinc-700 rounded text-zinc-500">
            <RefreshCw size={11} />
          </button>
          <input type="file" accept=".har" ref={fileInputRef} onChange={handleUpload} className="hidden" />
          <button
            onClick={() => fileInputRef.current?.click()}
            className="p-1 hover:bg-zinc-200 dark:hover:bg-zinc-700 rounded text-zinc-500"
            title="Upload HAR"
          >
            <Upload size={11} />
          </button>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto">
        {uploading && (
          <div className="flex items-center gap-2 px-3 py-2 text-xs text-blue-600">
            <Loader size={12} className="animate-spin" /> Uploading…
          </div>
        )}
        {files.length === 0 && !uploading && (
          <p className="px-3 py-4 text-xs text-zinc-400 dark:text-zinc-500">No HAR files found.</p>
        )}
        {files.map((f) => (
          <div
            key={f.name}
            onClick={() => onSelect(f)}
            className={`border-b border-zinc-100 dark:border-zinc-800 px-3 py-2 cursor-pointer transition-colors ${
              selectedFile?.name === f.name
                ? 'bg-blue-50 dark:bg-blue-900/20 border-l-2 border-l-blue-500'
                : 'hover:bg-zinc-100 dark:hover:bg-zinc-800'
            }`}
          >
            <p className="text-xs font-medium text-zinc-800 dark:text-zinc-200 truncate">{f.name}</p>
            <p className="text-[10px] text-zinc-400">{f.size_mb} MB</p>
            <button
              onClick={(e) => { e.stopPropagation(); handleImportAccount(f); }}
              className="mt-1 text-[9px] px-1.5 py-0.5 bg-green-50 dark:bg-green-900/20 text-green-600 dark:text-green-400 rounded border border-green-200 dark:border-green-800 hover:bg-green-100"
            >
              Import Account
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Entry Detail Panel ────────────────────────────────────────────────────────

function EntryDetail({
  entry, onClose, accounts,
}: {
  entry: HAREntry;
  onClose: () => void;
  accounts: string[];
}) {
  const [tab, setTab] = useState<'request' | 'response'>('request');
  const [selectedAccount, setSelectedAccount] = useState(accounts[0] ?? '');
  const [tryResult, setTryResult] = useState<null | { status: number; body: string; latency_ms: number }>(null);
  const [trying, setTrying] = useState(false);

  const handleTry = async () => {
    setTrying(true);
    setTryResult(null);
    try {
      const r = await fetch('/api/rpc/proxy', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: entry.url,
          method: entry.method,
          account_name: selectedAccount,
          headers: entry.request_headers,
          body: entry.request_body,
        }),
      });
      const data = await r.json();
      setTryResult(data);
    } finally {
      setTrying(false);
    }
  };

  const generatePythonCode = () => {
    const lines = [
      'import requests',
      '',
      'headers = {',
      ...Object.entries(entry.request_headers).map(([k, v]) => `    ${JSON.stringify(k)}: ${JSON.stringify(v)},`),
      '}',
      '',
      `resp = requests.${entry.method.toLowerCase()}(`,
      `    ${JSON.stringify(entry.url)},`,
      '    headers=headers,',
      entry.request_body ? `    data=${JSON.stringify(entry.request_body)},` : '',
      ')',
      'print(resp.status_code, resp.text[:500])',
    ].filter(Boolean);
    return lines.join('\n');
  };

  const handleCopyPython = () => {
    navigator.clipboard.writeText(generatePythonCode()).catch(() => {});
  };

  const handleCopyResponse = () => {
    navigator.clipboard.writeText(entry.response_body).catch(() => {});
  };

  return (
    <div className="flex flex-col h-full bg-white dark:bg-zinc-900 border-l border-zinc-200 dark:border-zinc-800 w-80 shrink-0">
      <div className="flex items-center justify-between px-3 py-2 border-b border-zinc-200 dark:border-zinc-800 shrink-0">
        <span className="text-xs font-semibold text-zinc-700 dark:text-zinc-300 truncate max-w-[180px]">
          Entry Detail
        </span>
        <button onClick={onClose} className="text-zinc-400 hover:text-zinc-600 text-xs px-1">✕</button>
      </div>

      {/* URL + method */}
      <div className="px-3 py-2 border-b border-zinc-100 dark:border-zinc-800 shrink-0 space-y-1">
        <div className="flex items-center gap-2">
          <MethodBadge method={entry.method} />
          <StatusBadge status={entry.status} />
          <span className="text-[10px] text-zinc-400">{entry.time_ms}ms</span>
        </div>
        <p className="text-[10px] text-zinc-600 dark:text-zinc-400 break-all leading-tight">{entry.url}</p>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-zinc-200 dark:border-zinc-800 shrink-0">
        {(['request', 'response'] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`flex-1 py-1.5 text-xs font-medium transition-colors ${
              tab === t
                ? 'text-blue-600 dark:text-blue-400 border-b-2 border-blue-500'
                : 'text-zinc-500 dark:text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-300'
            }`}
          >
            {t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-2 space-y-2">
        {tab === 'request' ? (
          <>
            <div>
              <h5 className="text-[10px] font-semibold text-zinc-500 dark:text-zinc-400 uppercase mb-1">Headers</h5>
              <div className="space-y-0.5">
                {Object.entries(entry.request_headers).slice(0, 12).map(([k, v]) => (
                  <div key={k} className="flex gap-1 text-[10px]">
                    <span className="text-zinc-400 shrink-0 min-w-0 truncate max-w-[100px]">{k}:</span>
                    <span className="text-zinc-700 dark:text-zinc-300 break-all">{String(v).slice(0, 60)}</span>
                  </div>
                ))}
              </div>
            </div>
            {entry.request_body && (
              <div>
                <h5 className="text-[10px] font-semibold text-zinc-500 dark:text-zinc-400 uppercase mb-1">Body</h5>
                <pre className="text-[10px] bg-zinc-50 dark:bg-zinc-800/50 border border-zinc-200 dark:border-zinc-700 rounded p-1.5 overflow-auto max-h-32 whitespace-pre-wrap text-zinc-700 dark:text-zinc-300">
                  {tryFormatJSON(entry.request_body)}
                </pre>
              </div>
            )}
          </>
        ) : (
          <>
            <div>
              <h5 className="text-[10px] font-semibold text-zinc-500 dark:text-zinc-400 uppercase mb-1">Body</h5>
              <pre className="text-[10px] bg-zinc-50 dark:bg-zinc-800/50 border border-zinc-200 dark:border-zinc-700 rounded p-1.5 overflow-auto max-h-48 whitespace-pre-wrap text-zinc-700 dark:text-zinc-300">
                {tryFormatJSON(entry.response_body)}
              </pre>
            </div>
          </>
        )}
      </div>

      {/* Actions */}
      <div className="border-t border-zinc-200 dark:border-zinc-800 px-3 py-2 space-y-2 shrink-0">
        <div className="flex gap-1">
          <select
            value={selectedAccount}
            onChange={(e) => setSelectedAccount(e.target.value)}
            className="flex-1 text-[10px] px-1.5 py-1 border border-zinc-300 dark:border-zinc-700 rounded bg-white dark:bg-zinc-800 dark:text-zinc-200"
          >
            {accounts.length === 0 && <option value="">No accounts</option>}
            {accounts.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
          <button
            onClick={handleTry}
            disabled={trying}
            className="flex items-center gap-1 px-2 py-1 text-[10px] bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
          >
            {trying ? <Loader size={9} className="animate-spin" /> : <Play size={9} />} Try
          </button>
        </div>
        <button
          onClick={handleCopyPython}
          className="w-full text-[10px] py-1 flex items-center justify-center gap-1 bg-zinc-100 dark:bg-zinc-800 hover:bg-zinc-200 dark:hover:bg-zinc-700 rounded text-zinc-600 dark:text-zinc-400"
        >
          <Copy size={9} /> Copy as Python requests
        </button>
        {tryResult && (
          <div className="p-1.5 bg-zinc-50 dark:bg-zinc-800 rounded border border-zinc-200 dark:border-zinc-700">
            <div className="flex gap-2 text-[10px] text-zinc-500 mb-1">
              <StatusBadge status={tryResult.status} />
              <span>{tryResult.latency_ms}ms</span>
            </div>
            <pre className="text-[10px] text-zinc-700 dark:text-zinc-300 whitespace-pre-wrap max-h-24 overflow-auto">
              {tryFormatJSON(tryResult.body).slice(0, 500)}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Entry Browser ─────────────────────────────────────────────────────────────

function EntryBrowser({
  file, accounts,
}: {
  file: HARFile;
  accounts: string[];
}) {
  const [entries, setEntries] = useState<HAREntry[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedEntry, setSelectedEntry] = useState<HAREntry | null>(null);
  const [method, setMethod] = useState('');
  const [urlSearch, setUrlSearch] = useState('');
  const [page, setPage] = useState(0);
  const PAGE_SIZE = 100;

  const loadEntries = async (reset = true) => {
    setLoading(true);
    setError(null);
    if (reset) {
      setEntries([]);
      setPage(0);
    }
    const offset = reset ? 0 : page * PAGE_SIZE;
    const params = new URLSearchParams({
      offset: String(offset),
      limit: String(PAGE_SIZE),
      ...(method && { method }),
      ...(urlSearch && { url_search: urlSearch }),
    });
    try {
      const r = await fetch(`/api/har/${file.name}/entries?${params}`);
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || 'Failed');
      setEntries(data.entries ?? []);
      setTotal(data.total ?? 0);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadEntries(true); }, [file.name]);

  return (
    <div className="flex flex-1 overflow-hidden">
      <div className="flex flex-col flex-1 overflow-hidden">
        {/* Filter bar */}
        <div className="flex items-center gap-2 px-3 py-2 border-b border-zinc-200 dark:border-zinc-800 shrink-0 bg-zinc-50 dark:bg-zinc-900/50">
          <select
            value={method}
            onChange={(e) => setMethod(e.target.value)}
            className="text-xs px-1.5 py-1 border border-zinc-300 dark:border-zinc-700 rounded bg-white dark:bg-zinc-800 dark:text-zinc-200"
          >
            <option value="">All Methods</option>
            {['GET', 'POST', 'PUT', 'DELETE', 'PATCH'].map((m) => <option key={m}>{m}</option>)}
          </select>
          <div className="flex flex-1 items-center gap-1 px-2 py-1 border border-zinc-300 dark:border-zinc-700 rounded bg-white dark:bg-zinc-800">
            <Search size={11} className="text-zinc-400 shrink-0" />
            <input
              value={urlSearch}
              onChange={(e) => setUrlSearch(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && loadEntries(true)}
              placeholder="Filter by URL…"
              className="flex-1 text-xs bg-transparent outline-none dark:text-zinc-200"
            />
          </div>
          <button
            onClick={() => loadEntries(true)}
            className="flex items-center gap-1 px-2 py-1 text-xs bg-zinc-800 dark:bg-zinc-100 text-white dark:text-zinc-900 rounded hover:bg-zinc-700"
          >
            <Filter size={11} /> Filter
          </button>
          <span className="text-[10px] text-zinc-400 shrink-0">{total} entries</span>
        </div>

        {/* Table */}
        <div className="flex-1 overflow-y-auto">
          {loading && (
            <div className="flex items-center justify-center py-8 text-zinc-400">
              <Loader size={18} className="animate-spin" />
            </div>
          )}
          {error && (
            <div className="flex items-center gap-2 px-4 py-3 text-sm text-red-600 dark:text-red-400">
              <AlertCircle size={14} /> {error}
            </div>
          )}
          {!loading && entries.map((e, i) => (
            <div
              key={i}
              onClick={() => setSelectedEntry(e)}
              className={`flex items-center gap-2 px-3 py-1.5 border-b border-zinc-100 dark:border-zinc-800 cursor-pointer transition-colors ${
                selectedEntry === e
                  ? 'bg-blue-50 dark:bg-blue-900/20'
                  : 'hover:bg-zinc-50 dark:hover:bg-zinc-800/50'
              }`}
            >
              <MethodBadge method={e.method} />
              <span className="flex-1 text-xs font-mono text-zinc-700 dark:text-zinc-300 truncate">
                {truncateUrl(e.url)}
              </span>
              <StatusBadge status={e.status} />
              <span className="text-[10px] text-zinc-400 shrink-0 w-14 text-right">{e.time_ms}ms</span>
            </div>
          ))}
        </div>

        {/* Bottom toolbar */}
        <div className="flex items-center justify-between px-3 py-1.5 border-t border-zinc-200 dark:border-zinc-800 shrink-0 bg-zinc-50 dark:bg-zinc-900/50">
          <div className="flex flex-wrap gap-1">
            <button
              onClick={() => {
                setMethod('POST');
                setUrlSearch('$rpc');
                setTimeout(() => loadEntries(true), 50);
              }}
              className="flex items-center gap-1 px-2 py-0.5 text-[10px] bg-zinc-100 dark:bg-zinc-800 hover:bg-zinc-200 dark:hover:bg-zinc-700 rounded text-zinc-600 dark:text-zinc-400"
            >
              <Database size={9} /> RPC Endpoints
            </button>
            <button
              onClick={() => {
                setMethod('');
                setUrlSearch('githubcopilot.com');
                setTimeout(() => loadEntries(true), 50);
              }}
              className="flex items-center gap-1 px-2 py-0.5 text-[10px] bg-zinc-100 dark:bg-zinc-800 hover:bg-zinc-200 dark:hover:bg-zinc-700 rounded text-zinc-600 dark:text-zinc-400"
            >
              <Github size={9} /> Copilot API
            </button>
            <button
              onClick={() => {
                setMethod('POST');
                setUrlSearch('colab');
                setTimeout(() => loadEntries(true), 50);
              }}
              className="flex items-center gap-1 px-2 py-0.5 text-[10px] bg-zinc-100 dark:bg-zinc-800 hover:bg-zinc-200 dark:hover:bg-zinc-700 rounded text-zinc-600 dark:text-zinc-400"
            >
              <Globe size={9} /> Colab
            </button>
            <button
              onClick={() => {
                setMethod('POST');
                setUrlSearch('notebooklm');
                setTimeout(() => loadEntries(true), 50);
              }}
              className="flex items-center gap-1 px-2 py-0.5 text-[10px] bg-zinc-100 dark:bg-zinc-800 hover:bg-zinc-200 dark:hover:bg-zinc-700 rounded text-zinc-600 dark:text-zinc-400"
            >
              <Globe size={9} /> NLM
            </button>
            <button
              onClick={() => {
                setMethod('');
                setUrlSearch('cookie');
                setTimeout(() => loadEntries(true), 50);
              }}
              className="flex items-center gap-1 px-2 py-0.5 text-[10px] bg-zinc-100 dark:bg-zinc-800 hover:bg-zinc-200 dark:hover:bg-zinc-700 rounded text-zinc-600 dark:text-zinc-400"
            >
              <Key size={9} /> Auth
            </button>
            <button
              onClick={() => {
                setMethod('');
                setUrlSearch('');
                setTimeout(() => loadEntries(true), 50);
              }}
              className="flex items-center gap-1 px-2 py-0.5 text-[10px] bg-zinc-100 dark:bg-zinc-800 hover:bg-zinc-200 dark:hover:bg-zinc-700 rounded text-zinc-600 dark:text-zinc-400"
            >
              ✕ Clear
            </button>
          </div>
        </div>
      </div>

      {/* Detail panel */}
      {selectedEntry && (
        <EntryDetail
          entry={selectedEntry}
          onClose={() => setSelectedEntry(null)}
          accounts={accounts}
        />
      )}
    </div>
  );
}

// ── Analysis Panel ────────────────────────────────────────────────────────────

function AnalysisPanel({ file }: { file: HARFile }) {
  const [analysis, setAnalysis] = useState<any | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await fetch(`/api/har/${encodeURIComponent(file.name)}/analyze`);
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || 'Analysis failed');
      setAnalysis(data);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { run(); }, [file.name]);

  if (loading) {
    return (
      <div className="flex items-center justify-center flex-1 text-zinc-400">
        <Loader size={20} className="animate-spin mr-2" />
        <span className="text-sm">Analyzing {file.name}…{file.size_mb > 50 ? ' (large file, streaming)' : ''}</span>
      </div>
    );
  }
  if (error) {
    return (
      <div className="flex items-center gap-2 p-4 text-red-600 dark:text-red-400">
        <AlertCircle size={16} /> {error}
      </div>
    );
  }
  if (!analysis) return null;

  const statusColors: Record<number, string> = {
    2: 'text-emerald-600 dark:text-emerald-400',
    3: 'text-blue-600 dark:text-blue-400',
    4: 'text-amber-600 dark:text-amber-400',
    5: 'text-red-600 dark:text-red-400',
  };

  return (
    <div className="flex-1 overflow-y-auto p-4 space-y-4">
      {/* Summary row */}
      <div className="grid grid-cols-4 gap-3">
        {[
          { label: 'Total Entries', value: analysis.total_entries?.toLocaleString() },
          { label: 'Unique Domains', value: analysis.unique_domains?.length },
          { label: 'Cookies', value: analysis.cookies_found?.length },
          { label: 'Methods', value: Object.keys(analysis.methods || {}).join(', ') },
        ].map(({ label, value }) => (
          <div key={label} className="bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded p-3">
            <p className="text-[10px] text-zinc-500 dark:text-zinc-400 uppercase font-semibold">{label}</p>
            <p className="text-lg font-bold text-zinc-900 dark:text-zinc-100">{value}</p>
          </div>
        ))}
      </div>

      {/* Auth detection */}
      <div className="grid grid-cols-2 gap-3">
        <div className={`flex items-center gap-2 px-3 py-2 rounded border ${
          analysis.has_github_auth
            ? 'bg-emerald-50 dark:bg-emerald-900/20 border-emerald-200 dark:border-emerald-800 text-emerald-700 dark:text-emerald-400'
            : 'bg-zinc-50 dark:bg-zinc-800 border-zinc-200 dark:border-zinc-700 text-zinc-400'
        }`}>
          <Github size={14} />
          <span className="text-xs font-medium">GitHub Auth {analysis.has_github_auth ? '✓ FOUND' : '— not found'}</span>
          {analysis.gh_bearer_found && <span className="text-[10px] ml-auto">GitHub-Bearer</span>}
        </div>
        <div className={`flex items-center gap-2 px-3 py-2 rounded border ${
          analysis.has_google_auth
            ? 'bg-blue-50 dark:bg-blue-900/20 border-blue-200 dark:border-blue-800 text-blue-700 dark:text-blue-400'
            : 'bg-zinc-50 dark:bg-zinc-800 border-zinc-200 dark:border-zinc-700 text-zinc-400'
        }`}>
          <Shield size={14} />
          <span className="text-xs font-medium">Google Auth {analysis.has_google_auth ? '✓ FOUND' : '— not found'}</span>
          {analysis.sapisid_found && <span className="text-[10px] ml-auto">SAPISID</span>}
        </div>
      </div>

      {/* Interesting domains */}
      {analysis.interesting_domains?.length > 0 && (
        <div className="bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded p-3">
          <h4 className="text-[10px] font-semibold text-zinc-500 dark:text-zinc-400 uppercase mb-2 flex items-center gap-1">
            <Globe size={10} /> Interesting Domains
          </h4>
          <div className="flex flex-wrap gap-1">
            {analysis.interesting_domains.map((d: string) => (
              <span key={d} className="px-2 py-0.5 text-[10px] bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 rounded border border-blue-200 dark:border-blue-800 font-mono">
                {d}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Status distribution */}
      <div className="bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded p-3">
        <h4 className="text-[10px] font-semibold text-zinc-500 dark:text-zinc-400 uppercase mb-2 flex items-center gap-1">
          <BarChart2 size={10} /> Status Distribution
        </h4>
        <div className="flex flex-wrap gap-2">
          {Object.entries(analysis.status_distribution || {}).map(([status, count]) => {
            const prefix = Math.floor(parseInt(status) / 100);
            return (
              <div key={status} className={`text-xs font-mono ${statusColors[prefix] ?? 'text-zinc-500'}`}>
                {status}: <span className="font-bold">{count as number}</span>
              </div>
            );
          })}
        </div>
      </div>

      {/* All cookies */}
      {analysis.cookies_found?.length > 0 && (
        <div className="bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded p-3">
          <h4 className="text-[10px] font-semibold text-zinc-500 dark:text-zinc-400 uppercase mb-2 flex items-center gap-1">
            <Key size={10} /> Cookie Names ({analysis.cookies_found.length})
          </h4>
          <div className="flex flex-wrap gap-1 max-h-24 overflow-y-auto">
            {analysis.cookies_found.map((c: string) => (
              <span key={c} className="px-1.5 py-0.5 text-[9px] bg-zinc-100 dark:bg-zinc-700 text-zinc-600 dark:text-zinc-400 rounded font-mono">{c}</span>
            ))}
          </div>
        </div>
      )}

      <button
        onClick={run}
        className="flex items-center gap-1 px-3 py-1.5 text-xs bg-zinc-100 dark:bg-zinc-800 hover:bg-zinc-200 dark:hover:bg-zinc-700 rounded text-zinc-600 dark:text-zinc-400"
      >
        <RefreshCw size={11} /> Re-analyze
      </button>
    </div>
  );
}

// ── Main Panel ────────────────────────────────────────────────────────────────

export default function HarExplorerPanel() {
  const [files, setFiles] = useState<HARFile[]>([]);
  const [selectedFile, setSelectedFile] = useState<HARFile | null>(null);
  const [accounts, setAccounts] = useState<string[]>([]);
  const [mainTab, setMainTab] = useState<'entries' | 'analyze'>('entries');

  const loadFiles = async () => {
    try {
      const r = await fetch('/api/har/list');
      const data = await r.json();
      setFiles(data.files ?? []);
    } catch {}
  };

  useEffect(() => {
    loadFiles();
    fetch('/api/accounts/list')
      .then((r) => r.json())
      .then((d) => setAccounts((d.accounts ?? []).map((a: any) => a.name)))
      .catch(() => {});
  }, []);

  return (
    <div className="flex h-full w-full overflow-hidden">
      <HarSidebar files={files} selectedFile={selectedFile} onSelect={(f) => { setSelectedFile(f); setMainTab('entries'); }} onRefresh={loadFiles} />
      <div className="flex flex-col flex-1 overflow-hidden">
        {selectedFile ? (
          <>
            {/* Header + tabs */}
            <div className="flex items-center gap-3 px-4 py-2 border-b border-zinc-200 dark:border-zinc-800 shrink-0 bg-zinc-50 dark:bg-zinc-900/50">
              <FileText size={13} className="text-zinc-400" />
              <span className="text-sm font-medium text-zinc-800 dark:text-zinc-200">{selectedFile.name}</span>
              <span className="text-xs text-zinc-400">{selectedFile.size_mb} MB</span>
              <div className="ml-auto flex gap-1">
                {(['entries', 'analyze'] as const).map((t) => (
                  <button
                    key={t}
                    onClick={() => setMainTab(t)}
                    className={`px-3 py-1 text-xs rounded font-medium transition-colors ${
                      mainTab === t
                        ? 'bg-blue-600 text-white'
                        : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-200 dark:hover:bg-zinc-700'
                    }`}
                  >
                    {t === 'analyze' ? <span className="flex items-center gap-1"><BarChart2 size={11} />Analyze</span> : 'Entries'}
                  </button>
                ))}
              </div>
            </div>
            {mainTab === 'entries' && <EntryBrowser file={selectedFile} accounts={accounts} />}
            {mainTab === 'analyze' && (
              <div className="flex flex-1 overflow-hidden">
                <AnalysisPanel file={selectedFile} />
              </div>
            )}
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center text-zinc-400 dark:text-zinc-500">
            <div className="text-center space-y-2">
              <FileText size={36} className="mx-auto opacity-30" />
              <p className="text-sm">Select a HAR file to browse entries</p>
              <p className="text-xs text-zinc-400">Supports files up to 300MB+ via streaming</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
