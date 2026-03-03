/**
 * RpcExplorerPanel — Build, send, and replay RPC requests through the Python sidecar.
 *
 * Layout: request builder (left) + response viewer (right), saved collection (bottom drawer).
 */

import React, { useState, useEffect, useCallback } from 'react';
import {
  Send, Plus, Trash2, Loader, Copy, ChevronDown, History,
  BookOpen, AlertCircle, Check,
} from 'lucide-react';
import { RpcRequest, RpcHistoryEntry, RpcTemplate } from '../types';
import { v4 as uuidv4 } from 'uuid';

// ── RPC Templates ─────────────────────────────────────────────────────────────

const RPC_TEMPLATES: RpcTemplate[] = [
  // ── Google Colab Agent ─────────────────────────────────────────────────────
  {
    label: 'Colab: AgentCreateTask',
    url: 'https://colab.clients6.google.com/$rpc/google.colab.v1.AgentService/CreateAgentTask',
    method: 'POST',
    content_type: 'application/json+protobuf',
    body: '[null,1]',
  },
  {
    label: 'Colab: AgentUpdateTask',
    url: 'https://colab.clients6.google.com/$rpc/google.colab.v1.AgentService/UpdateAgentTask',
    method: 'POST',
    content_type: 'application/json+protobuf',
    body: '[null,"TASK_ID_HERE","Your prompt here"]',
  },
  {
    label: 'Colab: AgentQueryTask',
    url: 'https://colab.clients6.google.com/$rpc/google.colab.v1.AgentService/QueryAgentTask',
    method: 'POST',
    content_type: 'application/json+protobuf',
    body: '[null,"TASK_ID_HERE"]',
  },
  {
    label: 'Colab: GetUserInfo',
    url: 'https://colab.clients6.google.com/$rpc/google.colab.v1.UserInfoService/GetUserInfo',
    method: 'POST',
    content_type: 'application/json+protobuf',
    body: '[null]',
  },
  {
    label: 'Colab: ListAssignments',
    url: 'https://colab.clients6.google.com/$rpc/google.colab.v1.RuntimeService/ListAssignments',
    method: 'POST',
    content_type: 'application/json+protobuf',
    body: '[null]',
  },
  // ── NotebookLM ─────────────────────────────────────────────────────────────
  {
    label: 'NLM: GenerateFreeFormStreamed',
    url: 'https://notebooklm.google.com/$rpc/google.internal.apps.maestro.ui.MaestroUiService/GenerateFreeFormStreamed',
    method: 'POST',
    content_type: 'application/json+protobuf',
    body: '[[["NOTEBOOK_ID_HERE","Your question here",null,null,[],null,null,[]]]]',
  },
  {
    label: 'NLM: CreateNotebook',
    url: 'https://notebooklm.google.com/$rpc/google.internal.apps.maestro.ui.MaestroUiService/CreateProject',
    method: 'POST',
    content_type: 'application/json+protobuf',
    body: '[["New Notebook","Description here"]]',
  },
  {
    label: 'NLM: ListNotebooks',
    url: 'https://notebooklm.google.com/$rpc/google.internal.apps.maestro.ui.MaestroUiService/ListProjects',
    method: 'POST',
    content_type: 'application/json+protobuf',
    body: '[[]]',
  },
  // ── GitHub Copilot ─────────────────────────────────────────────────────────
  {
    label: 'Copilot: Get Token',
    url: 'https://github.com/github-copilot/chat/token',
    method: 'POST',
    content_type: 'application/json',
    body: '{}',
  },
  {
    label: 'Copilot: List Models',
    url: 'https://api.individual.githubcopilot.com/models',
    method: 'GET',
    content_type: 'application/json',
    body: '',
  },
  {
    label: 'Copilot: Create Thread',
    url: 'https://api.individual.githubcopilot.com/github/chat/threads',
    method: 'POST',
    content_type: 'application/json',
    body: '{}',
  },
  {
    label: 'Copilot: Send Message',
    url: 'https://api.individual.githubcopilot.com/github/chat/threads/THREAD_ID_HERE/messages',
    method: 'POST',
    content_type: 'application/json',
    body: JSON.stringify({
      content: 'Hello, reply with exactly: test ok',
      intent: 'conversation',
      model: 'claude-sonnet-4.6',
      mode: 'immersive',
      parentMessageID: 'root',
      streaming: true,
      skillOptions: { deepCodeSearch: false },
    }, null, 2),
  },
];

// ── Helpers ──────────────────────────────────────────────────────────────────

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

function StatusBadge({ status }: { status: number }) {
  const cls = status >= 500 ? 'bg-red-100 text-red-700 dark:bg-red-900/50 dark:text-red-300'
    : status >= 400 ? 'bg-amber-100 text-amber-700 dark:bg-amber-900/50 dark:text-amber-300'
    : status >= 300 ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/50 dark:text-blue-300'
    : 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/50 dark:text-emerald-300';
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-bold ${cls}`}>{status}</span>
  );
}

// ── Header Row table ──────────────────────────────────────────────────────────

interface KVRow { key: string; value: string; }

function KVTable({
  rows, onChange, label,
}: {
  rows: KVRow[];
  onChange: (rows: KVRow[]) => void;
  label: string;
}) {
  const add = () => onChange([...rows, { key: '', value: '' }]);
  const remove = (i: number) => onChange(rows.filter((_, j) => j !== i));
  const update = (i: number, field: 'key' | 'value', val: string) => {
    const next = [...rows];
    next[i] = { ...next[i], [field]: val };
    onChange(next);
  };

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <label className="text-[10px] font-semibold text-zinc-500 dark:text-zinc-400 uppercase">{label}</label>
        <button onClick={add} className="p-0.5 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300">
          <Plus size={11} />
        </button>
      </div>
      {rows.map((row, i) => (
        <div key={i} className="flex gap-1">
          <input
            value={row.key}
            onChange={(e) => update(i, 'key', e.target.value)}
            placeholder="Header"
            className="flex-1 text-xs px-1.5 py-0.5 border border-zinc-300 dark:border-zinc-700 rounded bg-white dark:bg-zinc-800 dark:text-zinc-200"
          />
          <input
            value={row.value}
            onChange={(e) => update(i, 'value', e.target.value)}
            placeholder="Value"
            className="flex-1 text-xs px-1.5 py-0.5 border border-zinc-300 dark:border-zinc-700 rounded bg-white dark:bg-zinc-800 dark:text-zinc-200"
          />
          <button onClick={() => remove(i)} className="p-0.5 text-zinc-400 hover:text-red-500">
            <Trash2 size={11} />
          </button>
        </div>
      ))}
    </div>
  );
}

// ── Request Builder ───────────────────────────────────────────────────────────

function RequestBuilder({
  accounts,
  onSend,
  onSaveToCollection,
  initialRequest,
}: {
  accounts: string[];
  onSend: (req: Omit<RpcRequest, 'id'>) => Promise<void>;
  onSaveToCollection: (req: Omit<RpcRequest, 'id'> & { label: string }) => void;
  initialRequest?: RpcRequest | null;
}) {
  const [url, setUrl] = useState('');
  const [method, setMethod] = useState<'GET' | 'POST' | 'PUT' | 'DELETE'>('POST');
  const [account, setAccount] = useState(accounts[0] ?? '');
  const [headers, setHeaders] = useState<KVRow[]>([
    { key: 'x-goog-authuser', value: '0' },
    { key: 'x-same-domain', value: '1' },
  ]);
  const [body, setBody] = useState('');
  const [contentType, setContentType] = useState('application/json+protobuf');
  const [sending, setSending] = useState(false);
  const [savedLabel, setSavedLabel] = useState('');
  const [showSaveForm, setShowSaveForm] = useState(false);

  useEffect(() => {
    if (accounts.length > 0 && !account) setAccount(accounts[0]);
  }, [accounts]);

  useEffect(() => {
    if (initialRequest) {
      setUrl(initialRequest.url);
      setMethod(initialRequest.method as any);
      setAccount(initialRequest.account_name);
      setHeaders(Object.entries(initialRequest.headers).map(([key, value]) => ({ key, value })));
      setBody(initialRequest.body);
      setContentType(initialRequest.content_type);
    }
  }, [initialRequest]);

  const applyTemplate = (tmpl: RpcTemplate) => {
    setUrl(tmpl.url);
    setMethod(tmpl.method as any);
    setContentType(tmpl.content_type);
    setBody(tmpl.body);
  };

  const buildRequest = (): Omit<RpcRequest, 'id'> => ({
    url,
    method,
    account_name: account,
    headers: Object.fromEntries(headers.filter(r => r.key).map(r => [r.key, r.value])),
    body,
    content_type: contentType,
  });

  const handleSend = async () => {
    if (!url) return;
    setSending(true);
    try {
      await onSend(buildRequest());
    } finally {
      setSending(false);
    }
  };

  const handleSave = () => {
    if (!savedLabel) return;
    onSaveToCollection({ ...buildRequest(), label: savedLabel });
    setSavedLabel('');
    setShowSaveForm(false);
  };

  return (
    <div className="flex flex-col h-full w-[420px] shrink-0 border-r border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900">
      <div className="px-3 py-2 border-b border-zinc-200 dark:border-zinc-800 shrink-0">
        <h3 className="text-xs font-semibold text-zinc-600 dark:text-zinc-400 uppercase tracking-wider">Request Builder</h3>
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {/* Template picker */}
        <div className="relative">
          <label className="text-[10px] font-semibold text-zinc-500 dark:text-zinc-400 uppercase block mb-1">Template</label>
          <select
            onChange={(e) => {
              const t = RPC_TEMPLATES.find(t => t.label === e.target.value);
              if (t) applyTemplate(t);
              e.target.value = '';
            }}
            defaultValue=""
            className="w-full text-xs px-2 py-1 border border-zinc-300 dark:border-zinc-700 rounded bg-white dark:bg-zinc-800 dark:text-zinc-200"
          >
            <option value="">Select a template…</option>
            {RPC_TEMPLATES.map((t) => <option key={t.label} value={t.label}>{t.label}</option>)}
          </select>
        </div>

        {/* URL + Method */}
        <div className="flex gap-1">
          <select
            value={method}
            onChange={(e) => setMethod(e.target.value as any)}
            className="text-xs px-2 py-1 border border-zinc-300 dark:border-zinc-700 rounded bg-white dark:bg-zinc-800 dark:text-zinc-200"
          >
            {['GET', 'POST', 'PUT', 'DELETE'].map((m) => <option key={m}>{m}</option>)}
          </select>
          <input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://colab.clients6.google.com/$rpc/..."
            className="flex-1 text-xs px-2 py-1 border border-zinc-300 dark:border-zinc-700 rounded bg-white dark:bg-zinc-800 dark:text-zinc-200"
          />
        </div>

        {/* Account selector */}
        <div>
          <label className="text-[10px] font-semibold text-zinc-500 dark:text-zinc-400 uppercase block mb-1">Account (cookies)</label>
          <select
            value={account}
            onChange={(e) => setAccount(e.target.value)}
            className="w-full text-xs px-2 py-1 border border-zinc-300 dark:border-zinc-700 rounded bg-white dark:bg-zinc-800 dark:text-zinc-200"
          >
            <option value="">No account (anonymous)</option>
            {accounts.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
        </div>

        {/* Content-Type */}
        <div>
          <label className="text-[10px] font-semibold text-zinc-500 dark:text-zinc-400 uppercase block mb-1">Content-Type</label>
          <input
            value={contentType}
            onChange={(e) => setContentType(e.target.value)}
            className="w-full text-xs px-2 py-1 border border-zinc-300 dark:border-zinc-700 rounded bg-white dark:bg-zinc-800 dark:text-zinc-200"
          />
        </div>

        {/* Headers */}
        <KVTable rows={headers} onChange={setHeaders} label="Headers" />

        {/* Body */}
        <div>
          <label className="text-[10px] font-semibold text-zinc-500 dark:text-zinc-400 uppercase block mb-1">Body</label>
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={6}
            className="w-full text-xs font-mono px-2 py-1.5 border border-zinc-300 dark:border-zinc-700 rounded bg-white dark:bg-zinc-800 dark:text-zinc-200 resize-none"
            placeholder="[null,1]"
          />
        </div>
      </div>

      {/* Actions */}
      <div className="border-t border-zinc-200 dark:border-zinc-800 p-3 space-y-2 shrink-0">
        <button
          onClick={handleSend}
          disabled={sending || !url}
          className="w-full flex items-center justify-center gap-2 py-1.5 text-sm font-medium bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
        >
          {sending ? <Loader size={14} className="animate-spin" /> : <Send size={14} />}
          Send
        </button>
        {showSaveForm ? (
          <div className="flex gap-1">
            <input
              value={savedLabel}
              onChange={(e) => setSavedLabel(e.target.value)}
              placeholder="Label…"
              className="flex-1 text-xs px-1.5 py-1 border border-zinc-300 dark:border-zinc-700 rounded bg-white dark:bg-zinc-800 dark:text-zinc-200"
            />
            <button onClick={handleSave} className="px-2 py-1 text-xs bg-zinc-800 dark:bg-zinc-100 text-white dark:text-zinc-900 rounded">
              <Check size={11} />
            </button>
          </div>
        ) : (
          <button
            onClick={() => setShowSaveForm(true)}
            className="w-full text-xs py-1 flex items-center justify-center gap-1 bg-zinc-100 dark:bg-zinc-800 hover:bg-zinc-200 dark:hover:bg-zinc-700 rounded text-zinc-600 dark:text-zinc-400"
          >
            <Plus size={11} /> Add to Collection
          </button>
        )}
      </div>
    </div>
  );
}

// ── Response Viewer ───────────────────────────────────────────────────────────

function ResponseViewer({
  result, history, onRestore,
}: {
  result: RpcHistoryEntry['response'] | null;
  history: RpcHistoryEntry[];
  onRestore: (entry: RpcHistoryEntry) => void;
}) {
  const [showHistory, setShowHistory] = useState(false);

  const handleCopy = () => {
    if (result) navigator.clipboard.writeText(result.body).catch(() => {});
  };

  const formatted = result ? tryFormatJSON(result.body) : null;
  const isNLM = result && result.body.includes('wrb.fr');

  const extractNLMText = (body: string): string => {
    try {
      const cleaned = stripXSSI(body);
      const parsed = JSON.parse(cleaned);
      // NLM responses have text in nested arrays
      const text: string[] = [];
      JSON.stringify(parsed, (_, v) => {
        if (typeof v === 'string' && v.length > 20) text.push(v);
        return v;
      });
      return text.slice(0, 10).join('\n\n');
    } catch {
      return body;
    }
  };

  return (
    <div className="flex flex-col flex-1 overflow-hidden bg-zinc-50 dark:bg-zinc-900/50">
      <div className="flex items-center justify-between px-3 py-2 border-b border-zinc-200 dark:border-zinc-800 shrink-0">
        <h3 className="text-xs font-semibold text-zinc-600 dark:text-zinc-400 uppercase tracking-wider">Response</h3>
        <div className="flex gap-1">
          {result && (
            <button onClick={handleCopy} className="p-1 hover:bg-zinc-200 dark:hover:bg-zinc-700 rounded text-zinc-500">
              <Copy size={11} />
            </button>
          )}
          <button
            onClick={() => setShowHistory(!showHistory)}
            className={`p-1 rounded text-zinc-500 hover:bg-zinc-200 dark:hover:bg-zinc-700 ${showHistory ? 'bg-zinc-200 dark:bg-zinc-700' : ''}`}
            title="History"
          >
            <History size={11} />
          </button>
        </div>
      </div>

      {/* Status bar */}
      {result && (
        <div className="flex items-center gap-3 px-3 py-1.5 border-b border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shrink-0">
          <StatusBadge status={result.status} />
          <span className="text-[10px] text-zinc-400">{result.latency_ms}ms</span>
          {isNLM && (
            <button
              onClick={() => navigator.clipboard.writeText(extractNLMText(result.body)).catch(() => {})}
              className="text-[10px] px-1.5 py-0.5 bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400 rounded"
            >
              Parse as NLM
            </button>
          )}
        </div>
      )}

      {/* Body */}
      <div className="flex-1 overflow-auto p-3">
        {!result && !showHistory && (
          <div className="flex items-center justify-center h-full text-zinc-400 dark:text-zinc-500">
            <div className="text-center space-y-2">
              <Send size={28} className="mx-auto opacity-30" />
              <p className="text-sm">Send a request to see the response</p>
            </div>
          </div>
        )}
        {result && !showHistory && (
          <pre className="text-xs font-mono text-zinc-700 dark:text-zinc-300 whitespace-pre-wrap break-all">
            {formatted}
          </pre>
        )}
        {showHistory && (
          <div className="space-y-2">
            <h4 className="text-xs font-semibold text-zinc-500 dark:text-zinc-400 uppercase">Last {history.length} requests</h4>
            {history.length === 0 && (
              <p className="text-xs text-zinc-400 dark:text-zinc-500">No history yet.</p>
            )}
            {[...history].reverse().map((h) => (
              <div
                key={h.id}
                onClick={() => { onRestore(h); setShowHistory(false); }}
                className="flex items-center gap-2 px-2 py-1.5 bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded cursor-pointer hover:bg-zinc-50 dark:hover:bg-zinc-700"
              >
                <StatusBadge status={h.response.status} />
                <span className="flex-1 text-[10px] font-mono text-zinc-600 dark:text-zinc-400 truncate">{h.request.url}</span>
                <span className="text-[10px] text-zinc-400">{h.response.latency_ms}ms</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Saved Collection Drawer ───────────────────────────────────────────────────

function CollectionDrawer({
  collection, onLoad, onDelete, onRunAll,
}: {
  collection: (RpcRequest & { label: string })[];
  onLoad: (req: RpcRequest) => void;
  onDelete: (id: string) => void;
  onRunAll: () => void;
}) {
  const [open, setOpen] = useState(false);

  return (
    <div className="border-t border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shrink-0">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center justify-between w-full px-3 py-2 text-xs font-semibold text-zinc-600 dark:text-zinc-400 uppercase tracking-wider hover:bg-zinc-50 dark:hover:bg-zinc-800"
      >
        <span className="flex items-center gap-1.5">
          <BookOpen size={11} /> Saved Collection ({collection.length})
        </span>
        <ChevronDown size={11} className={`transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <div className="border-t border-zinc-100 dark:border-zinc-800 max-h-40 overflow-y-auto">
          <div className="flex justify-end px-3 py-1 border-b border-zinc-100 dark:border-zinc-800">
            <button
              onClick={onRunAll}
              className="flex items-center gap-1 text-[10px] px-2 py-0.5 bg-blue-600 text-white rounded hover:bg-blue-700"
            >
              <Send size={9} /> Run All
            </button>
          </div>
          {collection.length === 0 && (
            <p className="px-3 py-2 text-xs text-zinc-400 dark:text-zinc-500">No saved requests.</p>
          )}
          {collection.map((req) => (
            <div
              key={req.id}
              className="flex items-center justify-between px-3 py-1.5 border-b border-zinc-100 dark:border-zinc-800 hover:bg-zinc-50 dark:hover:bg-zinc-800"
            >
              <button
                onClick={() => onLoad(req)}
                className="flex-1 text-left text-xs text-zinc-700 dark:text-zinc-300 truncate"
              >
                {req.label}
              </button>
              <button
                onClick={() => onDelete(req.id)}
                className="p-0.5 text-zinc-400 hover:text-red-500"
              >
                <Trash2 size={10} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Main Panel ────────────────────────────────────────────────────────────────

export default function RpcExplorerPanel() {
  const [accounts, setAccounts] = useState<string[]>([]);
  const [history, setHistory] = useState<RpcHistoryEntry[]>([]);
  const [currentResult, setCurrentResult] = useState<RpcHistoryEntry['response'] | null>(null);
  const [collection, setCollection] = useState<(RpcRequest & { label: string })[]>([]);
  const [restoredRequest, setRestoredRequest] = useState<RpcRequest | null>(null);

  useEffect(() => {
    fetch('/api/accounts/list')
      .then((r) => r.json())
      .then((d) => setAccounts((d.accounts ?? []).map((a: any) => a.name)))
      .catch(() => {});
  }, []);

  const handleSend = useCallback(async (req: Omit<RpcRequest, 'id'>) => {
    const r = await fetch('/api/rpc/proxy', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    });
    const data = await r.json();
    const entry: RpcHistoryEntry = {
      id: uuidv4(),
      request: { ...req, id: uuidv4() },
      response: {
        status: data.status ?? r.status,
        body: data.body ?? JSON.stringify(data),
        headers: data.headers ?? {},
        latency_ms: data.latency_ms ?? 0,
      },
      timestamp: Date.now(),
    };
    setCurrentResult(entry.response);
    setHistory((prev) => [...prev.slice(-19), entry]);
  }, []);

  const handleSaveToCollection = (req: Omit<RpcRequest, 'id'> & { label: string }) => {
    setCollection((prev) => [...prev, { ...req, id: uuidv4() }]);
  };

  const handleRunAll = async () => {
    for (const req of collection) {
      await handleSend(req);
      await new Promise((r) => setTimeout(r, 800));
    }
  };

  const handleRestore = (entry: RpcHistoryEntry) => {
    setRestoredRequest(entry.request);
    setCurrentResult(entry.response);
  };

  return (
    <div className="flex flex-col h-full w-full overflow-hidden">
      <div className="flex flex-1 overflow-hidden">
        <RequestBuilder
          accounts={accounts}
          onSend={handleSend}
          onSaveToCollection={handleSaveToCollection}
          initialRequest={restoredRequest}
        />
        <ResponseViewer result={currentResult} history={history} onRestore={handleRestore} />
      </div>
      <CollectionDrawer
        collection={collection}
        onLoad={(req) => setRestoredRequest(req)}
        onDelete={(id) => setCollection((prev) => prev.filter((r) => r.id !== id))}
        onRunAll={handleRunAll}
      />
    </div>
  );
}
