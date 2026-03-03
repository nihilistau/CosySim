/**
 * NexusPanel (enhanced) — Real-time Nexus knowledge interface.
 *
 * Tabs: Entries | Q&A Cache | Rules
 */

import React, { useState, useEffect } from 'react';
import {
  Search, Plus, X, Database, Tag, Loader, ChevronRight,
  MessageSquare, Shield, RefreshCw, Check, Edit2,
} from 'lucide-react';

// ── Types ─────────────────────────────────────────────────────────────────────

interface NexusEntry {
  id: string;
  title: string;
  content: string;
  category: string;
  content_type: string;
  created_at?: string;
}

interface QAEntry {
  id?: string;
  question: string;
  answer: string;
  category: string;
  created_at?: string;
}

interface Rule {
  id?: string;
  scope: string;
  rule: string;
  priority?: number;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

const CATEGORY_COLORS: Record<string, string> = {
  architecture: 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/50 dark:text-indigo-300',
  debugging:    'bg-red-100 text-red-700 dark:bg-red-900/50 dark:text-red-300',
  api:          'bg-blue-100 text-blue-700 dark:bg-blue-900/50 dark:text-blue-300',
  testing:      'bg-green-100 text-green-700 dark:bg-green-900/50 dark:text-green-300',
  performance:  'bg-amber-100 text-amber-700 dark:bg-amber-900/50 dark:text-amber-300',
  system:       'bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400',
};

const TYPE_COLORS: Record<string, string> = {
  note:     'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400',
  code:     'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/50 dark:text-emerald-300',
  document: 'bg-purple-100 text-purple-700 dark:bg-purple-900/50 dark:text-purple-300',
  decision: 'bg-orange-100 text-orange-700 dark:bg-orange-900/50 dark:text-orange-300',
  prompt:   'bg-pink-100 text-pink-700 dark:bg-pink-900/50 dark:text-pink-300',
};

const categoryClass = (cat: string) =>
  CATEGORY_COLORS[cat?.toLowerCase()] ?? 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400';
const typeClass = (type: string) =>
  TYPE_COLORS[type?.toLowerCase()] ?? 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400';

// ── Tab: Entries ──────────────────────────────────────────────────────────────

function EntriesTab() {
  const [entries, setEntries] = useState<NexusEntry[]>([]);
  const [query, setQuery] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedEntry, setSelectedEntry] = useState<NexusEntry | null>(null);
  const [answerCard, setAnswerCard] = useState<string | null>(null);

  const [isAddingEntry, setIsAddingEntry] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [newContent, setNewContent] = useState('');
  const [newCategory, setNewCategory] = useState('architecture');
  const [newType, setNewType] = useState('note');
  const [addError, setAddError] = useState<string | null>(null);
  const [isAdding, setIsAdding] = useState(false);

  const handleSearch = async () => {
    if (!query.trim()) return;
    setIsLoading(true);
    setError(null);
    setAnswerCard(null);
    try {
      const r = await fetch('/api/nexus/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: query.trim(), limit: 20 }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      setEntries(data.results ?? []);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setIsLoading(false);
    }
  };

  const handleAsk = async () => {
    if (!query.trim()) return;
    setIsLoading(true);
    setError(null);
    try {
      const r = await fetch('/api/nexus/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: query.trim() }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      setAnswerCard(data.answer ?? '');
    } catch (e: any) {
      setError(e.message);
    } finally {
      setIsLoading(false);
    }
  };

  const handleAddEntry = async () => {
    if (!newTitle.trim() || !newContent.trim()) {
      setAddError('Title and content are required.');
      return;
    }
    setIsAdding(true);
    setAddError(null);
    try {
      const r = await fetch('/api/nexus/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: newTitle, content: newContent, content_type: newType, category: newCategory }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setNewTitle(''); setNewContent(''); setIsAddingEntry(false);
    } catch (e: any) {
      setAddError(e.message);
    } finally {
      setIsAdding(false);
    }
  };

  return (
    <div className="flex h-full overflow-hidden">
      {/* Entry list */}
      <div className="flex flex-col w-80 shrink-0 border-r border-zinc-200 dark:border-zinc-800">
        {/* Search bar */}
        <div className="p-3 border-b border-zinc-200 dark:border-zinc-800 space-y-2">
          <div className="flex items-center gap-1 px-2 py-1 border border-zinc-300 dark:border-zinc-700 rounded bg-white dark:bg-zinc-800">
            <Search size={13} className="text-zinc-400 shrink-0" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
              placeholder="Search Nexus…"
              className="flex-1 text-xs bg-transparent outline-none dark:text-zinc-200"
            />
            {isLoading && <Loader size={13} className="text-zinc-400 animate-spin shrink-0" />}
          </div>
          <div className="flex gap-1">
            <button
              onClick={handleSearch}
              className="flex-1 py-1 text-xs bg-zinc-800 dark:bg-zinc-100 text-white dark:text-zinc-900 rounded hover:bg-zinc-700 dark:hover:bg-zinc-200"
            >
              Search
            </button>
            <button
              onClick={handleAsk}
              className="flex-1 py-1 text-xs bg-violet-600 text-white rounded hover:bg-violet-700"
            >
              Ask
            </button>
          </div>
        </div>

        {/* Results */}
        <div className="flex-1 overflow-y-auto">
          {error && (
            <div className="px-3 py-2 text-xs text-red-500">{error}</div>
          )}
          {answerCard && (
            <div className="mx-3 my-2 p-2 bg-violet-50 dark:bg-violet-900/20 border border-violet-200 dark:border-violet-800 rounded text-xs text-violet-800 dark:text-violet-300 leading-relaxed">
              {answerCard}
            </div>
          )}
          {entries.map((entry) => (
            <div
              key={entry.id}
              onClick={() => setSelectedEntry(entry)}
              className={`px-3 py-2 border-b border-zinc-100 dark:border-zinc-800 cursor-pointer transition-colors ${
                selectedEntry?.id === entry.id
                  ? 'bg-blue-50 dark:bg-blue-900/20 border-l-2 border-l-blue-500'
                  : 'hover:bg-zinc-50 dark:hover:bg-zinc-800/50'
              }`}
            >
              <div className="flex items-center gap-1.5 mb-0.5">
                <span className={`px-1.5 py-0.5 rounded text-[9px] font-medium ${typeClass(entry.content_type)}`}>
                  {entry.content_type}
                </span>
                <span className={`px-1.5 py-0.5 rounded text-[9px] font-medium ${categoryClass(entry.category)}`}>
                  {entry.category}
                </span>
              </div>
              <p className="text-xs font-medium text-zinc-800 dark:text-zinc-200 truncate">{entry.title}</p>
              {entry.created_at && (
                <p className="text-[10px] text-zinc-400">{new Date(entry.created_at).toLocaleDateString()}</p>
              )}
            </div>
          ))}
        </div>

        {/* Add entry */}
        <div className="border-t border-zinc-200 dark:border-zinc-800 p-3 shrink-0">
          {!isAddingEntry ? (
            <button
              onClick={() => setIsAddingEntry(true)}
              className="w-full flex items-center justify-center gap-1 py-1.5 text-xs bg-zinc-800 dark:bg-zinc-100 text-white dark:text-zinc-900 rounded hover:bg-zinc-700"
            >
              <Plus size={12} /> Add Entry
            </button>
          ) : (
            <div className="space-y-2">
              <input
                value={newTitle}
                onChange={(e) => setNewTitle(e.target.value)}
                placeholder="Title"
                className="w-full text-xs px-2 py-1 border border-zinc-300 dark:border-zinc-700 rounded bg-white dark:bg-zinc-800 dark:text-zinc-200"
              />
              <textarea
                value={newContent}
                onChange={(e) => setNewContent(e.target.value)}
                rows={3}
                placeholder="Content"
                className="w-full text-xs px-2 py-1 border border-zinc-300 dark:border-zinc-700 rounded bg-white dark:bg-zinc-800 dark:text-zinc-200 resize-none"
              />
              <div className="flex gap-1">
                <select value={newType} onChange={(e) => setNewType(e.target.value)}
                  className="flex-1 text-xs px-1.5 py-1 border border-zinc-300 dark:border-zinc-700 rounded bg-white dark:bg-zinc-800 dark:text-zinc-200">
                  {['note', 'code', 'document', 'decision', 'prompt'].map((t) => <option key={t}>{t}</option>)}
                </select>
                <select value={newCategory} onChange={(e) => setNewCategory(e.target.value)}
                  className="flex-1 text-xs px-1.5 py-1 border border-zinc-300 dark:border-zinc-700 rounded bg-white dark:bg-zinc-800 dark:text-zinc-200">
                  {['architecture', 'api', 'debugging', 'testing', 'performance', 'system', 'general'].map((c) => <option key={c}>{c}</option>)}
                </select>
              </div>
              {addError && <p className="text-[10px] text-red-500">{addError}</p>}
              <div className="flex gap-1">
                <button
                  onClick={handleAddEntry}
                  disabled={isAdding}
                  className="flex-1 flex items-center justify-center gap-1 py-1 text-xs bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
                >
                  {isAdding ? <Loader size={11} className="animate-spin" /> : <Check size={11} />} Save
                </button>
                <button
                  onClick={() => { setIsAddingEntry(false); setAddError(null); }}
                  className="px-2 py-1 text-xs bg-zinc-200 dark:bg-zinc-700 text-zinc-600 dark:text-zinc-400 rounded"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Entry detail */}
      <div className="flex-1 overflow-y-auto p-4">
        {selectedEntry ? (
          <div className="space-y-3">
            <div className="flex items-start justify-between gap-2">
              <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">{selectedEntry.title}</h2>
              <div className="flex gap-1 shrink-0">
                <span className={`px-1.5 py-0.5 rounded text-[10px] ${typeClass(selectedEntry.content_type)}`}>
                  {selectedEntry.content_type}
                </span>
                <span className={`px-1.5 py-0.5 rounded text-[10px] ${categoryClass(selectedEntry.category)}`}>
                  {selectedEntry.category}
                </span>
              </div>
            </div>
            <pre className="text-xs text-zinc-700 dark:text-zinc-300 bg-zinc-50 dark:bg-zinc-800 rounded p-3 whitespace-pre-wrap leading-relaxed overflow-auto max-h-96 border border-zinc-200 dark:border-zinc-700">
              {selectedEntry.content}
            </pre>
          </div>
        ) : (
          <div className="flex items-center justify-center h-full text-zinc-400 dark:text-zinc-500">
            <div className="text-center space-y-2">
              <Database size={32} className="mx-auto opacity-30" />
              <p className="text-sm">Select an entry to view details</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Tab: Q&A Cache ────────────────────────────────────────────────────────────

function QATab() {
  const [qaList, setQaList] = useState<QAEntry[]>([]);
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState('');
  const [category, setCategory] = useState('general');
  const [saving, setSaving] = useState(false);
  const [savedOk, setSavedOk] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSave = async () => {
    if (!question.trim() || !answer.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const r = await fetch('/api/nexus/qa', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, answer, category }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const newEntry: QAEntry = { question, answer, category, created_at: new Date().toISOString() };
      setQaList((prev) => [newEntry, ...prev]);
      setQuestion(''); setAnswer('');
      setSavedOk(true);
      setTimeout(() => setSavedOk(false), 2000);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const handleSearch = async () => {
    if (!question.trim()) return;
    try {
      const r = await fetch('/api/nexus/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question }),
      });
      const data = await r.json();
      if (data.answer) setAnswer(data.answer);
    } catch {}
  };

  return (
    <div className="flex h-full overflow-hidden">
      {/* Q&A List */}
      <div className="w-80 shrink-0 border-r border-zinc-200 dark:border-zinc-800 overflow-y-auto">
        <div className="px-3 py-2 border-b border-zinc-200 dark:border-zinc-800">
          <h4 className="text-xs font-semibold text-zinc-600 dark:text-zinc-400 uppercase tracking-wider flex items-center gap-1">
            <MessageSquare size={11} /> Cached Q&A
          </h4>
        </div>
        {qaList.length === 0 && (
          <p className="px-3 py-4 text-xs text-zinc-400 dark:text-zinc-500">No cached Q&A pairs in this session.</p>
        )}
        {qaList.map((qa, i) => (
          <div
            key={i}
            onClick={() => { setQuestion(qa.question); setAnswer(qa.answer); }}
            className="border-b border-zinc-100 dark:border-zinc-800 px-3 py-2 cursor-pointer hover:bg-zinc-50 dark:hover:bg-zinc-800"
          >
            <p className="text-xs font-medium text-zinc-800 dark:text-zinc-200 truncate">Q: {qa.question}</p>
            <p className="text-[10px] text-zinc-400 truncate">A: {qa.answer}</p>
            <div className="flex gap-1 mt-0.5">
              <span className={`px-1 py-0.5 rounded text-[9px] ${categoryClass(qa.category)}`}>{qa.category}</span>
            </div>
          </div>
        ))}
      </div>

      {/* Add Q&A form */}
      <div className="flex-1 p-4 space-y-3 overflow-y-auto">
        <h4 className="text-sm font-semibold text-zinc-800 dark:text-zinc-200">Add Q&A Pair</h4>
        <div>
          <label className="text-[10px] font-semibold text-zinc-500 uppercase block mb-1">Question</label>
          <div className="flex gap-1">
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              rows={2}
              placeholder="What question was answered?"
              className="flex-1 text-xs px-2 py-1.5 border border-zinc-300 dark:border-zinc-700 rounded bg-white dark:bg-zinc-800 dark:text-zinc-200 resize-none"
            />
            <button
              onClick={handleSearch}
              className="px-2 py-1 text-[10px] bg-violet-600 text-white rounded hover:bg-violet-700 self-start"
              title="Look up answer in Nexus"
            >
              Ask
            </button>
          </div>
        </div>
        <div>
          <label className="text-[10px] font-semibold text-zinc-500 uppercase block mb-1">Answer</label>
          <textarea
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            rows={5}
            placeholder="The answer to cache…"
            className="w-full text-xs px-2 py-1.5 border border-zinc-300 dark:border-zinc-700 rounded bg-white dark:bg-zinc-800 dark:text-zinc-200 resize-none"
          />
        </div>
        <div className="flex items-center gap-2">
          <select value={category} onChange={(e) => setCategory(e.target.value)}
            className="text-xs px-1.5 py-1 border border-zinc-300 dark:border-zinc-700 rounded bg-white dark:bg-zinc-800 dark:text-zinc-200">
            {['general', 'architecture', 'api', 'debugging', 'testing', 'system'].map((c) => <option key={c}>{c}</option>)}
          </select>
          <button
            onClick={handleSave}
            disabled={saving || !question.trim() || !answer.trim()}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
          >
            {saving ? <Loader size={11} className="animate-spin" /> : savedOk ? <Check size={11} /> : <Plus size={11} />}
            {savedOk ? 'Saved!' : 'Save Q&A'}
          </button>
        </div>
        {error && <p className="text-xs text-red-500">{error}</p>}
      </div>
    </div>
  );
}

// ── Tab: Rules ────────────────────────────────────────────────────────────────

function RulesTab() {
  const [scope, setScope] = useState('global');
  const [rules, setRules] = useState<Rule[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadRules = async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await fetch(`/api/nexus/rules?scope=${encodeURIComponent(scope)}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      const raw = data.rules ?? [];
      setRules(Array.isArray(raw) ? raw.map((r: any) =>
        typeof r === 'string' ? { rule: r, scope } : r
      ) : []);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadRules(); }, [scope]);

  const SCOPES = ['global', 'coding', 'scene', 'testing', 'nexus', 'mcp'];

  return (
    <div className="flex h-full overflow-hidden">
      <div className="w-48 shrink-0 border-r border-zinc-200 dark:border-zinc-800 overflow-y-auto">
        <div className="px-3 py-2 border-b border-zinc-200 dark:border-zinc-800">
          <h4 className="text-xs font-semibold text-zinc-600 dark:text-zinc-400 uppercase tracking-wider flex items-center gap-1">
            <Shield size={11} /> Scopes
          </h4>
        </div>
        {SCOPES.map((s) => (
          <button
            key={s}
            onClick={() => setScope(s)}
            className={`w-full text-left px-3 py-2 text-xs transition-colors border-b border-zinc-100 dark:border-zinc-800 ${
              scope === s
                ? 'bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400 font-medium border-l-2 border-l-blue-500'
                : 'text-zinc-600 dark:text-zinc-400 hover:bg-zinc-50 dark:hover:bg-zinc-800'
            }`}
          >
            {s}
          </button>
        ))}
      </div>
      <div className="flex-1 overflow-y-auto p-4 space-y-2">
        <div className="flex items-center justify-between mb-3">
          <h4 className="text-sm font-semibold text-zinc-800 dark:text-zinc-200">Rules: {scope}</h4>
          <button onClick={loadRules} className="p-1 hover:bg-zinc-200 dark:hover:bg-zinc-700 rounded text-zinc-400">
            <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>
        {error && <p className="text-xs text-red-500">{error}</p>}
        {rules.length === 0 && !loading && (
          <p className="text-xs text-zinc-400 dark:text-zinc-500">No rules found for scope: {scope}</p>
        )}
        {loading && (
          <div className="flex items-center gap-2 text-xs text-zinc-400">
            <Loader size={13} className="animate-spin" /> Loading…
          </div>
        )}
        {rules.map((rule, i) => (
          <div key={i} className="flex items-start gap-2 p-2.5 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded">
            <ChevronRight size={12} className="text-zinc-400 shrink-0 mt-0.5" />
            <span className="text-xs text-zinc-700 dark:text-zinc-300 leading-relaxed">
              {rule.rule ?? JSON.stringify(rule)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Main Panel ────────────────────────────────────────────────────────────────

type Tab = 'entries' | 'qa' | 'rules';

export default function NexusPanel() {
  const [tab, setTab] = useState<Tab>('entries');

  const TABS: { id: Tab; label: string; icon: React.ReactNode }[] = [
    { id: 'entries', label: 'Entries', icon: <Database size={12} /> },
    { id: 'qa', label: 'Q&A Cache', icon: <MessageSquare size={12} /> },
    { id: 'rules', label: 'Rules', icon: <Shield size={12} /> },
  ];

  return (
    <div className="flex flex-col h-full w-full overflow-hidden">
      {/* Tab bar */}
      <div className="flex items-center border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900 shrink-0">
        {TABS.map(({ id, label, icon }) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={`flex items-center gap-1.5 px-4 py-2.5 text-xs font-medium border-b-2 transition-colors ${
              tab === id
                ? 'text-blue-600 dark:text-blue-400 border-blue-500'
                : 'text-zinc-500 dark:text-zinc-400 border-transparent hover:text-zinc-700 dark:hover:text-zinc-300'
            }`}
          >
            {icon} {label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-hidden">
        {tab === 'entries' && <EntriesTab />}
        {tab === 'qa' && <QATab />}
        {tab === 'rules' && <RulesTab />}
      </div>
    </div>
  );
}
