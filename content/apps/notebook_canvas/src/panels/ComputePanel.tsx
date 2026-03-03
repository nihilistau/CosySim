/**
 * ComputePanel — JIT compute lifecycle manager.
 *
 * Three-column layout:
 *   Col 1: Account Pool
 *   Col 2: Active Tunnels + JIT Config
 *   Col 3: Quick Inference
 */

import React, { useState, useEffect, useRef } from 'react';
import {
  Server, Zap, Activity, Settings, Upload, RefreshCw, Trash2,
  Check, AlertCircle, Cpu, Play, Loader, ChevronDown,
} from 'lucide-react';
import { ComputeAccount, TunnelSession, JITConfig } from '../types';

// ── Helpers ──────────────────────────────────────────────────────────────────

function TierBadge({ tier }: { tier: string }) {
  const cls = tier === 'pro'
    ? 'bg-purple-100 text-purple-700 dark:bg-purple-900/50 dark:text-purple-300'
    : tier === 'free'
    ? 'bg-green-100 text-green-700 dark:bg-green-900/50 dark:text-green-300'
    : 'bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400';
  return (
    <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold uppercase ${cls}`}>
      {tier}
    </span>
  );
}

function UsageBar({ used, limit, label }: { used: number; limit: number; label: string }) {
  const pct = limit > 0 ? Math.min(100, (used / limit) * 100) : 0;
  const color = pct > 80 ? 'bg-red-500' : pct > 50 ? 'bg-amber-500' : 'bg-emerald-500';
  return (
    <div className="space-y-0.5">
      <div className="flex justify-between text-[10px] text-zinc-500 dark:text-zinc-400">
        <span>{label}</span>
        <span>{used}/{limit}</span>
      </div>
      <div className="h-1.5 bg-zinc-200 dark:bg-zinc-700 rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function HealthDot({ healthy }: { healthy: boolean }) {
  return (
    <span className={`inline-block w-2 h-2 rounded-full ${healthy ? 'bg-emerald-500' : 'bg-red-500'}`} />
  );
}

// ── Column 1: Account Pool ───────────────────────────────────────────────────

function AccountPoolCol({
  accounts, onRefresh, onUnlockAll,
}: {
  accounts: ComputeAccount[];
  onRefresh: () => void;
  onUnlockAll: (name: string) => void;
}) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [importing, setImporting] = useState<string | null>(null);

  const handleHARImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setImporting(file.name);
    const form = new FormData();
    form.append('file', file);
    try {
      await fetch('http://localhost:5591/api/har/upload', { method: 'POST', body: form });
      await fetch('/api/har/import-account', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: `data/har_files/${file.name}`, account_name: file.name.replace('.har', '') }),
      });
      onRefresh();
    } finally {
      setImporting(null);
    }
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-3 py-2 border-b border-zinc-200 dark:border-zinc-800 shrink-0">
        <h3 className="text-xs font-semibold text-zinc-600 dark:text-zinc-400 uppercase tracking-wider flex items-center gap-1.5">
          <Server size={12} /> Account Pool
        </h3>
        <div className="flex gap-1">
          <button onClick={onRefresh} className="p-1 hover:bg-zinc-200 dark:hover:bg-zinc-700 rounded text-zinc-500">
            <RefreshCw size={12} />
          </button>
          <input type="file" accept=".har" ref={fileInputRef} onChange={handleHARImport} className="hidden" />
          <button
            onClick={() => fileInputRef.current?.click()}
            className="flex items-center gap-1 px-1.5 py-0.5 text-[10px] bg-blue-50 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400 rounded hover:bg-blue-100 dark:hover:bg-blue-900/50 border border-blue-200 dark:border-blue-800"
          >
            <Upload size={10} /> Import HAR
          </button>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto">
        {importing && (
          <div className="flex items-center gap-2 px-3 py-2 text-xs text-blue-600 dark:text-blue-400">
            <Loader size={12} className="animate-spin" /> Importing {importing}…
          </div>
        )}
        {accounts.length === 0 && (
          <p className="px-3 py-4 text-xs text-zinc-400 dark:text-zinc-500">
            No accounts found. Import a HAR file to add one.
          </p>
        )}
        {accounts.map((acct) => (
          <div key={acct.name} className="border-b border-zinc-100 dark:border-zinc-800 px-3 py-2 space-y-1.5">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-zinc-800 dark:text-zinc-200 truncate max-w-[110px]">
                {acct.name}
              </span>
              <div className="flex items-center gap-1">
                <TierBadge tier={acct.tier} />
                <button
                  onClick={() => onUnlockAll(acct.name)}
                  className="px-1 py-0.5 text-[9px] bg-amber-50 dark:bg-amber-900/20 text-amber-600 dark:text-amber-400 rounded border border-amber-200 dark:border-amber-800 hover:bg-amber-100"
                  title="Set all limits to unlimited"
                >
                  Unlock All
                </button>
              </div>
            </div>
            <div className="flex flex-wrap gap-1">
              {acct.services.map((s) => (
                <span key={s} className="px-1 py-0.5 text-[9px] bg-zinc-100 dark:bg-zinc-800 text-zinc-500 dark:text-zinc-400 rounded">
                  {s}
                </span>
              ))}
            </div>
            {Object.keys(acct.limits).slice(0, 2).map((key) => (
              <UsageBar
                key={key}
                label={key.replace('colab_', '').replace('_per_day', '/d')}
                used={acct.usage[key] ?? 0}
                limit={acct.limits[key]}
              />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Column 2: Tunnels + JIT Config ───────────────────────────────────────────

function TunnelsCol({
  sessions, accounts, jitConfig, onDeploy, onTeardown, onSaveJIT,
}: {
  sessions: TunnelSession[];
  accounts: ComputeAccount[];
  jitConfig: JITConfig;
  onDeploy: (accountName: string, tunnelType: string) => Promise<void>;
  onTeardown: (id: string) => Promise<void>;
  onSaveJIT: (cfg: JITConfig) => void;
}) {
  const [deployAccount, setDeployAccount] = useState('');
  const [deployType, setDeployType] = useState<'cloudflare' | 'ngrok'>('cloudflare');
  const [deploying, setDeploying] = useState(false);
  const [cfg, setCfg] = useState<JITConfig>(jitConfig);

  useEffect(() => { setCfg(jitConfig); }, [jitConfig]);

  const handleDeploy = async () => {
    if (!deployAccount) return;
    setDeploying(true);
    try {
      await onDeploy(deployAccount, deployType);
    } finally {
      setDeploying(false);
    }
  };

  return (
    <div className="flex flex-col h-full">
      <div className="px-3 py-2 border-b border-zinc-200 dark:border-zinc-800 shrink-0">
        <h3 className="text-xs font-semibold text-zinc-600 dark:text-zinc-400 uppercase tracking-wider flex items-center gap-1.5">
          <Activity size={12} /> Active Tunnels
        </h3>
      </div>

      {/* Deploy form */}
      <div className="px-3 py-2 border-b border-zinc-100 dark:border-zinc-800 space-y-1.5 shrink-0">
        <div className="flex gap-1">
          <select
            value={deployAccount}
            onChange={(e) => setDeployAccount(e.target.value)}
            className="flex-1 text-xs px-1.5 py-1 border border-zinc-300 dark:border-zinc-700 rounded bg-white dark:bg-zinc-800 dark:text-zinc-200"
          >
            <option value="">Select account…</option>
            {accounts.map((a) => <option key={a.name} value={a.name}>{a.name}</option>)}
          </select>
          <select
            value={deployType}
            onChange={(e) => setDeployType(e.target.value as any)}
            className="text-xs px-1.5 py-1 border border-zinc-300 dark:border-zinc-700 rounded bg-white dark:bg-zinc-800 dark:text-zinc-200"
          >
            <option value="cloudflare">Cloudflare</option>
            <option value="ngrok">ngrok</option>
          </select>
        </div>
        <button
          onClick={handleDeploy}
          disabled={deploying || !deployAccount}
          className="w-full flex items-center justify-center gap-1.5 py-1 text-xs bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
        >
          {deploying ? <Loader size={11} className="animate-spin" /> : <Zap size={11} />}
          Deploy Tunnel
        </button>
      </div>

      {/* Session list */}
      <div className="flex-1 overflow-y-auto">
        {sessions.length === 0 && (
          <p className="px-3 py-4 text-xs text-zinc-400 dark:text-zinc-500">No active sessions.</p>
        )}
        {sessions.map((s) => (
          <div key={s.id} className="border-b border-zinc-100 dark:border-zinc-800 px-3 py-2 space-y-1">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-zinc-800 dark:text-zinc-200 truncate max-w-[120px]">
                {s.account_name}
              </span>
              <div className="flex items-center gap-1.5">
                <HealthDot healthy={s.healthy} />
                <button
                  onClick={() => onTeardown(s.id)}
                  className="p-0.5 text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 rounded"
                  title="Teardown"
                >
                  <Trash2 size={11} />
                </button>
              </div>
            </div>
            <a
              href={s.tunnel_url}
              target="_blank"
              rel="noopener noreferrer"
              className="block text-[10px] text-blue-500 hover:underline truncate"
            >
              {s.tunnel_url}
            </a>
            <div className="flex gap-2 text-[10px] text-zinc-400">
              <span><Cpu size={9} className="inline mr-0.5" />{s.hardware}</span>
              <span>{s.tunnel_type}</span>
              <span>{new Date(s.started_at * 1000).toLocaleTimeString()}</span>
            </div>
          </div>
        ))}
      </div>

      {/* JIT Config */}
      <div className="border-t border-zinc-200 dark:border-zinc-800 px-3 py-2 space-y-2 shrink-0">
        <h4 className="text-[10px] font-semibold text-zinc-500 dark:text-zinc-400 uppercase tracking-wider flex items-center gap-1">
          <Settings size={10} /> JIT Config
        </h4>
        <div className="grid grid-cols-2 gap-x-2 gap-y-1.5">
          <label className="text-[10px] text-zinc-500">Max session (min)</label>
          <input
            type="number" min={1} max={60} value={cfg.max_session_minutes}
            onChange={(e) => setCfg({ ...cfg, max_session_minutes: +e.target.value })}
            className="text-xs px-1.5 py-0.5 border border-zinc-300 dark:border-zinc-700 rounded bg-white dark:bg-zinc-800 dark:text-zinc-200 w-full"
          />
          <label className="text-[10px] text-zinc-500">Idle timeout (min)</label>
          <input
            type="number" min={1} max={30} value={cfg.idle_timeout_minutes}
            onChange={(e) => setCfg({ ...cfg, idle_timeout_minutes: +e.target.value })}
            className="text-xs px-1.5 py-0.5 border border-zinc-300 dark:border-zinc-700 rounded bg-white dark:bg-zinc-800 dark:text-zinc-200 w-full"
          />
          <label className="text-[10px] text-zinc-500">Human delays</label>
          <input type="checkbox" checked={cfg.human_delays}
            onChange={(e) => setCfg({ ...cfg, human_delays: e.target.checked })}
            className="self-center"
          />
          <label className="text-[10px] text-zinc-500">Delay range (s)</label>
          <div className="flex gap-1 items-center">
            <input
              type="number" step={0.1} min={0} value={cfg.min_delay_s}
              onChange={(e) => setCfg({ ...cfg, min_delay_s: +e.target.value })}
              className="text-xs px-1 py-0.5 border border-zinc-300 dark:border-zinc-700 rounded bg-white dark:bg-zinc-800 dark:text-zinc-200 w-12"
            />
            <span className="text-[9px] text-zinc-400">–</span>
            <input
              type="number" step={0.1} min={0} value={cfg.max_delay_s}
              onChange={(e) => setCfg({ ...cfg, max_delay_s: +e.target.value })}
              className="text-xs px-1 py-0.5 border border-zinc-300 dark:border-zinc-700 rounded bg-white dark:bg-zinc-800 dark:text-zinc-200 w-12"
            />
          </div>
        </div>
        <button
          onClick={() => onSaveJIT(cfg)}
          className="w-full flex items-center justify-center gap-1 py-1 text-xs bg-zinc-800 dark:bg-zinc-100 text-white dark:text-zinc-900 rounded hover:bg-zinc-700 dark:hover:bg-zinc-200"
        >
          <Check size={11} /> Save
        </button>
      </div>
    </div>
  );
}

// ── Column 3: Quick Inference ────────────────────────────────────────────────

function InferenceCol({ accounts }: { accounts: ComputeAccount[] }) {
  const [models, setModels] = useState<{ free: string[]; pro: string[] }>({ free: [], pro: [] });
  const [model, setModel] = useState('auto');
  const [tier, setTier] = useState<'free' | 'pro'>('free');
  const [prompt, setPrompt] = useState('');
  const [result, setResult] = useState<null | {
    response: string; backend: string; model: string; account: string; latency_ms: number;
  }>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch('/api/compute/models')
      .then((r) => r.json())
      .then(setModels)
      .catch(() => {});
  }, []);

  const handleInfer = async () => {
    if (!prompt.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const resp = await fetch('/api/compute/infer', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt, model, tier }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || 'Request failed');
      setResult(data);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const availableModels = tier === 'pro' ? models.pro : models.free;

  return (
    <div className="flex flex-col h-full">
      <div className="px-3 py-2 border-b border-zinc-200 dark:border-zinc-800 shrink-0">
        <h3 className="text-xs font-semibold text-zinc-600 dark:text-zinc-400 uppercase tracking-wider flex items-center gap-1.5">
          <Zap size={12} /> Quick Inference (JIT)
        </h3>
      </div>
      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {/* Tier toggle */}
        <div className="flex gap-1">
          {(['free', 'pro'] as const).map((t) => (
            <button
              key={t}
              onClick={() => { setTier(t); setModel('auto'); }}
              className={`flex-1 py-1 text-xs rounded border transition-colors ${
                tier === t
                  ? 'bg-zinc-800 dark:bg-zinc-100 text-white dark:text-zinc-900 border-zinc-800 dark:border-zinc-100'
                  : 'border-zinc-300 dark:border-zinc-700 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800'
              }`}
            >
              {t.toUpperCase()}
            </button>
          ))}
        </div>
        {/* Model selector */}
        <select
          value={model}
          onChange={(e) => setModel(e.target.value)}
          className="w-full text-xs px-2 py-1 border border-zinc-300 dark:border-zinc-700 rounded bg-white dark:bg-zinc-800 dark:text-zinc-200"
        >
          <option value="auto">auto (best available)</option>
          {availableModels.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
        {/* Prompt */}
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={5}
          placeholder="Enter prompt…"
          className="w-full text-xs px-2 py-1.5 border border-zinc-300 dark:border-zinc-700 rounded bg-white dark:bg-zinc-800 dark:text-zinc-200 resize-none"
        />
        <button
          onClick={handleInfer}
          disabled={loading || !prompt.trim()}
          className="w-full flex items-center justify-center gap-1.5 py-1.5 text-xs bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
        >
          {loading ? <Loader size={12} className="animate-spin" /> : <Play size={12} />}
          Route Inference
        </button>

        {error && (
          <div className="flex items-start gap-1.5 p-2 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded text-xs text-red-600 dark:text-red-400">
            <AlertCircle size={12} className="shrink-0 mt-0.5" />
            {error}
          </div>
        )}

        {result && (
          <div className="space-y-2">
            <div className="flex gap-2 text-[10px] text-zinc-500 dark:text-zinc-400">
              <span className="px-1.5 py-0.5 bg-zinc-100 dark:bg-zinc-800 rounded">{result.backend}</span>
              <span className="px-1.5 py-0.5 bg-zinc-100 dark:bg-zinc-800 rounded">{result.model}</span>
              <span className="px-1.5 py-0.5 bg-zinc-100 dark:bg-zinc-800 rounded">{result.latency_ms}ms</span>
              <span className="px-1.5 py-0.5 bg-zinc-100 dark:bg-zinc-800 rounded truncate max-w-[80px]">{result.account}</span>
            </div>
            <pre className="text-xs bg-zinc-50 dark:bg-zinc-800/50 border border-zinc-200 dark:border-zinc-700 rounded p-2 overflow-auto max-h-48 whitespace-pre-wrap text-zinc-700 dark:text-zinc-300">
              {result.response}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Main Panel ────────────────────────────────────────────────────────────────

export default function ComputePanel() {
  const [accounts, setAccounts] = useState<ComputeAccount[]>([]);
  const [sessions, setSessions] = useState<TunnelSession[]>([]);
  const [jitConfig, setJitConfig] = useState<JITConfig>({
    max_session_minutes: 25,
    idle_timeout_minutes: 5,
    human_delays: true,
    min_delay_s: 0.5,
    max_delay_s: 2.5,
  });

  const loadAccounts = async () => {
    try {
      const r = await fetch('/api/accounts/list');
      const data = await r.json();
      setAccounts(data.accounts ?? []);
    } catch {}
  };

  const loadSessions = async () => {
    try {
      const r = await fetch('/api/compute/tunnel/list');
      const data = await r.json();
      setSessions(data.sessions ?? []);
    } catch {}
  };

  useEffect(() => {
    loadAccounts();
    loadSessions();
    const iv = setInterval(() => loadSessions(), 15000);
    return () => clearInterval(iv);
  }, []);

  const handleUnlockAll = async (name: string) => {
    await fetch('/api/accounts/configure', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, service: 'colab_requests_per_day', limit: 1e18 }),
    });
    loadAccounts();
  };

  const handleDeploy = async (accountName: string, tunnelType: string) => {
    await fetch('/api/compute/tunnel/deploy', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ account_name: accountName, tunnel_type: tunnelType }),
    });
    loadSessions();
  };

  const handleTeardown = async (id: string) => {
    await fetch(`/api/compute/tunnel/${id}`, { method: 'DELETE' });
    loadSessions();
  };

  const handleSaveJIT = async (cfg: JITConfig) => {
    setJitConfig(cfg);
    // Persist via compute infer route (JIT config is stored server-side)
    await fetch('/api/compute/infer', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: '__jit_configure__', jit_config: cfg }),
    }).catch(() => {});
  };

  return (
    <div className="flex h-full w-full overflow-hidden">
      {/* Col 1 */}
      <div className="w-64 shrink-0 border-r border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900 flex flex-col">
        <AccountPoolCol accounts={accounts} onRefresh={loadAccounts} onUnlockAll={handleUnlockAll} />
      </div>
      {/* Col 2 */}
      <div className="w-72 shrink-0 border-r border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 flex flex-col">
        <TunnelsCol
          sessions={sessions}
          accounts={accounts}
          jitConfig={jitConfig}
          onDeploy={handleDeploy}
          onTeardown={handleTeardown}
          onSaveJIT={handleSaveJIT}
        />
      </div>
      {/* Col 3 */}
      <div className="flex-1 bg-white dark:bg-zinc-900 flex flex-col">
        <InferenceCol accounts={accounts} />
      </div>
    </div>
  );
}
