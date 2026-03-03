import React, { useState, useEffect } from 'react';
import { Key, RefreshCw, Upload, FolderOpen, CheckCircle, XCircle, AlertTriangle, Clock, Loader } from 'lucide-react';

interface GoogleAccount {
  account_id: string;
  service: string;
  cookie_count: number;
  has_api_key: boolean;
  rate_limited_until: number | null;
  last_used: number | null;
  request_count?: number;
}

interface Props {}

function formatRelativeTime(ts: number | null): string {
  if (ts == null) return 'never';
  const diffMs = Date.now() - ts * 1000;
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return 'just now';
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  return `${Math.floor(diffHr / 24)}d ago`;
}

function formatTime(ts: number | null): string {
  if (ts == null) return '';
  return new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export default function AccountsPanel({}: Props) {
  const [accounts, setAccounts] = useState<GoogleAccount[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [importPath, setImportPath] = useState('');
  const [importAccountId, setImportAccountId] = useState('');
  const [isImporting, setIsImporting] = useState(false);
  const [importResult, setImportResult] = useState<string | null>(null);
  const [importIsError, setImportIsError] = useState(false);

  const [dirPath, setDirPath] = useState('');
  const [isBulkImporting, setIsBulkImporting] = useState(false);

  const loadAccounts = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await fetch('/api/accounts');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setAccounts(data.accounts ?? data ?? []);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => { loadAccounts(); }, []);

  const handleImportHar = async () => {
    if (!importPath.trim()) return;
    setIsImporting(true);
    setImportResult(null);
    try {
      const res = await fetch('/api/accounts/import-har', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ har_path: importPath, account_id: importAccountId || undefined, service: 'google' }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setImportResult(data.message ?? 'Import successful');
      setImportIsError(false);
      setImportPath('');
      setImportAccountId('');
      loadAccounts();
    } catch (e: any) {
      setImportResult(e.message);
      setImportIsError(true);
    } finally {
      setIsImporting(false);
    }
  };

  const handleBulkImport = async () => {
    if (!dirPath.trim()) return;
    setIsBulkImporting(true);
    setImportResult(null);
    try {
      const res = await fetch('/api/accounts/import-directory', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ directory: dirPath }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setImportResult(data.message ?? `Imported ${data.imported ?? '?'} accounts`);
      setImportIsError(false);
      setDirPath('');
      loadAccounts();
    } catch (e: any) {
      setImportResult(e.message);
      setImportIsError(true);
    } finally {
      setIsBulkImporting(false);
    }
  };

  const now = Date.now() / 1000;
  const available = accounts.filter(a => !a.rate_limited_until || a.rate_limited_until < now);
  const rateLimited = accounts.filter(a => a.rate_limited_until && a.rate_limited_until >= now);

  return (
    <div className="flex flex-col h-full bg-white dark:bg-zinc-900 overflow-y-auto transition-colors">
      {/* Header */}
      <div className="h-14 border-b border-zinc-200 dark:border-zinc-800 flex items-center justify-between px-6 shrink-0 bg-zinc-50/50 dark:bg-zinc-900/50">
        <div className="flex items-center gap-2">
          <Key size={16} className="text-emerald-500" />
          <h1 className="text-sm font-bold tracking-widest text-zinc-700 dark:text-zinc-300 uppercase">Google Accounts</h1>
        </div>
        <button
          onClick={loadAccounts}
          disabled={isLoading}
          className="p-1.5 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800 rounded-lg transition-colors disabled:opacity-50"
        >
          <RefreshCw size={14} className={isLoading ? 'animate-spin' : ''} />
        </button>
      </div>

      <div className="p-6 space-y-6">
        {/* Summary */}
        {!error && (
          <div className="flex gap-4 text-sm">
            <span className="text-zinc-500 dark:text-zinc-400">{accounts.length} account{accounts.length !== 1 ? 's' : ''}</span>
            <span className="text-green-600 dark:text-green-400 font-medium">{available.length} available</span>
            {rateLimited.length > 0 && (
              <span className="text-red-500 dark:text-red-400">{rateLimited.length} rate-limited</span>
            )}
          </div>
        )}
        {error && <p className="text-sm text-red-400">{error}</p>}

        {/* Account cards */}
        <div className="space-y-3">
          {isLoading && accounts.length === 0 && (
            <div className="flex items-center justify-center h-16">
              <Loader size={18} className="animate-spin text-zinc-400" />
            </div>
          )}
          {accounts.length === 0 && !isLoading && (
            <p className="text-sm text-zinc-400 dark:text-zinc-500 italic">No accounts found. Import a HAR file to get started.</p>
          )}
          {accounts.map(account => {
            const isRateLimited = !!(account.rate_limited_until && account.rate_limited_until >= now);
            const noSapisid = !account.has_api_key && account.cookie_count === 0;
            return (
              <div
                key={account.account_id}
                className="p-4 bg-zinc-50 dark:bg-zinc-800/50 border border-zinc-200 dark:border-zinc-700 rounded-xl"
              >
                <div className="flex items-start justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <Key size={14} className="text-zinc-400 shrink-0 mt-0.5" />
                    <span className="text-sm font-semibold text-zinc-800 dark:text-zinc-100 font-mono">{account.account_id}</span>
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-zinc-200 dark:bg-zinc-700 text-zinc-600 dark:text-zinc-300">{account.service}</span>
                  </div>
                  {isRateLimited ? (
                    <span className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-red-100 dark:bg-red-900/40 text-red-600 dark:text-red-400">
                      <XCircle size={10} /> Rate Limited
                    </span>
                  ) : noSapisid ? (
                    <span className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-yellow-100 dark:bg-yellow-900/40 text-yellow-700 dark:text-yellow-400">
                      <AlertTriangle size={10} /> No SAPISID
                    </span>
                  ) : (
                    <span className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-400">
                      <CheckCircle size={10} /> Available
                    </span>
                  )}
                </div>
                <div className="grid grid-cols-2 gap-x-4 gap-y-1 mt-2">
                  <p className="text-xs text-zinc-500 dark:text-zinc-400">
                    <span className="text-zinc-400">Cookies:</span> <span className="font-medium text-zinc-700 dark:text-zinc-300">{account.cookie_count}</span>
                  </p>
                  <p className="text-xs text-zinc-500 dark:text-zinc-400">
                    <span className="text-zinc-400">API Key:</span>{' '}
                    {account.has_api_key
                      ? <span className="text-green-600 dark:text-green-400 font-medium">✓ Present</span>
                      : <span className="text-zinc-400">✗ None</span>}
                  </p>
                  <p className="text-xs text-zinc-500 dark:text-zinc-400">
                    <span className="text-zinc-400">Last used:</span> <span className="font-medium text-zinc-600 dark:text-zinc-300">{formatRelativeTime(account.last_used)}</span>
                  </p>
                  {isRateLimited && (
                    <p className="text-xs text-red-500 dark:text-red-400 flex items-center gap-1">
                      <Clock size={10} />
                      Limited until {formatTime(account.rate_limited_until)}
                    </p>
                  )}
                  {account.request_count != null && (
                    <p className="text-xs text-zinc-500 dark:text-zinc-400">
                      <span className="text-zinc-400">Requests:</span> <span className="font-medium text-zinc-600 dark:text-zinc-300">{account.request_count}</span>
                    </p>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        {/* Divider */}
        <div className="border-t border-zinc-200 dark:border-zinc-700 pt-4">
          <h2 className="text-xs font-semibold text-zinc-500 dark:text-zinc-400 uppercase tracking-widest mb-4">Import New Account</h2>
          <div className="space-y-3">
            <div>
              <label className="block text-xs font-medium text-zinc-600 dark:text-zinc-400 mb-1">HAR File Path</label>
              <input
                type="text"
                value={importPath}
                onChange={e => setImportPath(e.target.value)}
                placeholder="/path/to/file.har"
                className="w-full px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500 dark:text-zinc-200 transition-colors"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-zinc-600 dark:text-zinc-400 mb-1">Account ID <span className="font-normal text-zinc-400">(optional)</span></label>
              <input
                type="text"
                value={importAccountId}
                onChange={e => setImportAccountId(e.target.value)}
                placeholder="e.g. main_account"
                className="w-full px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500 dark:text-zinc-200 transition-colors"
              />
            </div>
            <div className="flex justify-end">
              <button
                onClick={handleImportHar}
                disabled={isImporting || !importPath.trim()}
                className="flex items-center gap-2 px-4 py-2 text-sm font-medium bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg disabled:opacity-50 transition-colors"
              >
                {isImporting ? <Loader size={14} className="animate-spin" /> : <Upload size={14} />}
                Import HAR
              </button>
            </div>
          </div>
        </div>

        {/* Bulk import */}
        <div className="border-t border-zinc-200 dark:border-zinc-700 pt-4">
          <h2 className="text-xs font-semibold text-zinc-500 dark:text-zinc-400 uppercase tracking-widest mb-4">Bulk Import</h2>
          <div className="space-y-3">
            <div>
              <label className="block text-xs font-medium text-zinc-600 dark:text-zinc-400 mb-1">Directory</label>
              <input
                type="text"
                value={dirPath}
                onChange={e => setDirPath(e.target.value)}
                placeholder="/path/to/har/directory"
                className="w-full px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500 dark:text-zinc-200 transition-colors"
              />
            </div>
            <div className="flex justify-end">
              <button
                onClick={handleBulkImport}
                disabled={isBulkImporting || !dirPath.trim()}
                className="flex items-center gap-2 px-4 py-2 text-sm font-medium bg-zinc-700 hover:bg-zinc-800 dark:bg-zinc-600 dark:hover:bg-zinc-500 text-white rounded-lg disabled:opacity-50 transition-colors"
              >
                {isBulkImporting ? <Loader size={14} className="animate-spin" /> : <FolderOpen size={14} />}
                Import All
              </button>
            </div>
          </div>
        </div>

        {/* Import result */}
        {importResult && (
          <div className={`p-3 rounded-lg text-sm ${importIsError ? 'bg-red-50 dark:bg-red-950/30 text-red-600 dark:text-red-400 border border-red-200 dark:border-red-800' : 'bg-green-50 dark:bg-green-950/30 text-green-700 dark:text-green-400 border border-green-200 dark:border-green-800'}`}>
            {importResult}
          </div>
        )}
      </div>
    </div>
  );
}
