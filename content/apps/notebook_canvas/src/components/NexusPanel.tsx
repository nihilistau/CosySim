import React, { useState, useEffect } from 'react';
import { Search, Plus, X, Database, Tag, Loader, ChevronRight } from 'lucide-react';

interface NexusEntry {
  id: string;
  title: string;
  content: string;
  category: string;
  content_type: string;
  created_at?: string;
}

interface Props {
  activeNotebookId: string | null;
}

const CATEGORY_COLORS: Record<string, string> = {
  architecture: 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/50 dark:text-indigo-300',
  debugging:    'bg-red-100 text-red-700 dark:bg-red-900/50 dark:text-red-300',
  api:          'bg-blue-100 text-blue-700 dark:bg-blue-900/50 dark:text-blue-300',
  testing:      'bg-green-100 text-green-700 dark:bg-green-900/50 dark:text-green-300',
  performance:  'bg-amber-100 text-amber-700 dark:bg-amber-900/50 dark:text-amber-300',
  system:       'bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400',
};
const categoryClass = (cat: string) =>
  CATEGORY_COLORS[cat?.toLowerCase()] ?? 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400';

export default function NexusPanel({ activeNotebookId }: Props) {
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
      const res = await fetch('/api/nexus/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setEntries(data.results ?? data ?? []);
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
    setAnswerCard(null);
    try {
      const res = await fetch('/api/nexus/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: query }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setAnswerCard(data.answer ?? JSON.stringify(data));
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
      const res = await fetch('/api/nexus/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: newTitle, content: newContent, content_type: newType, category: newCategory }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setNewTitle('');
      setNewContent('');
      setIsAddingEntry(false);
      handleSearch();
    } catch (e: any) {
      setAddError(e.message);
    } finally {
      setIsAdding(false);
    }
  };

  return (
    <div className="flex flex-col h-full bg-white dark:bg-zinc-900 transition-colors">
      {/* Header */}
      <div className="h-14 border-b border-zinc-200 dark:border-zinc-800 flex items-center justify-between px-6 shrink-0 bg-zinc-50/50 dark:bg-zinc-900/50">
        <div className="flex items-center gap-2">
          <Database size={16} className="text-indigo-500" />
          <h1 className="text-sm font-bold tracking-widest text-zinc-700 dark:text-zinc-300 uppercase">Nexus Knowledge</h1>
        </div>
        <button
          onClick={() => { setIsAddingEntry(v => !v); setAddError(null); }}
          className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded bg-indigo-600 hover:bg-indigo-700 text-white transition-colors"
        >
          <Plus size={13} />
          Add Entry
        </button>
      </div>

      {/* Search bar */}
      <div className="px-4 py-3 border-b border-zinc-200 dark:border-zinc-800 shrink-0">
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400" />
            <input
              type="text"
              value={query}
              onChange={e => setQuery(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') handleSearch(); }}
              placeholder="Search Nexus..."
              className="w-full pl-8 pr-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:text-zinc-200 transition-colors"
            />
          </div>
          <button
            onClick={handleAsk}
            disabled={isLoading || !query.trim()}
            className="px-3 py-2 text-xs font-medium rounded-lg bg-violet-600 hover:bg-violet-700 text-white disabled:opacity-50 transition-colors"
          >
            Ask
          </button>
          <button
            onClick={handleSearch}
            disabled={isLoading || !query.trim()}
            className="px-3 py-2 text-xs font-medium rounded-lg bg-zinc-800 dark:bg-zinc-700 hover:bg-zinc-700 dark:hover:bg-zinc-600 text-white disabled:opacity-50 transition-colors"
          >
            Search
          </button>
        </div>
        {error && <p className="mt-2 text-xs text-red-400">{error}</p>}
      </div>

      {/* Add Entry panel */}
      {isAddingEntry && (
        <div className="mx-4 mt-3 mb-1 p-4 bg-indigo-50 dark:bg-indigo-950/30 border border-indigo-200 dark:border-indigo-800 rounded-xl shrink-0">
          <div className="flex items-center justify-between mb-3">
            <span className="text-xs font-semibold text-indigo-700 dark:text-indigo-300 uppercase tracking-wide">New Entry</span>
            <button onClick={() => setIsAddingEntry(false)} className="text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200">
              <X size={14} />
            </button>
          </div>
          <div className="space-y-2">
            <input
              type="text"
              value={newTitle}
              onChange={e => setNewTitle(e.target.value)}
              placeholder="Title"
              className="w-full px-3 py-2 text-sm bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:text-zinc-200"
            />
            <textarea
              value={newContent}
              onChange={e => setNewContent(e.target.value)}
              placeholder="Content..."
              rows={4}
              className="w-full px-3 py-2 text-sm bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none dark:text-zinc-200"
            />
            <div className="flex gap-2">
              <select
                value={newCategory}
                onChange={e => setNewCategory(e.target.value)}
                className="flex-1 px-2 py-1.5 text-xs bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-lg dark:text-zinc-200"
              >
                {['architecture','api','debugging','testing','performance','system','general'].map(c => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
              <select
                value={newType}
                onChange={e => setNewType(e.target.value)}
                className="flex-1 px-2 py-1.5 text-xs bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-lg dark:text-zinc-200"
              >
                {['note','code','document','decision','prompt','memory'].map(t => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
              <button
                onClick={handleAddEntry}
                disabled={isAdding}
                className="px-4 py-1.5 text-xs font-medium bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg disabled:opacity-50 transition-colors flex items-center gap-1"
              >
                {isAdding ? <Loader size={12} className="animate-spin" /> : <Plus size={12} />}
                Add
              </button>
            </div>
            {addError && <p className="text-xs text-red-400">{addError}</p>}
          </div>
        </div>
      )}

      {/* Main content */}
      <div className="flex flex-1 overflow-hidden gap-0">
        {/* Results list */}
        <div className="w-2/5 border-r border-zinc-200 dark:border-zinc-800 overflow-y-auto">
          {isLoading && (
            <div className="flex items-center justify-center h-24">
              <Loader size={20} className="animate-spin text-indigo-500" />
            </div>
          )}

          {/* Answer card */}
          {answerCard && (
            <div className="m-3 p-3 bg-violet-50 dark:bg-violet-950/30 border border-violet-200 dark:border-violet-800 rounded-xl">
              <p className="text-xs font-semibold text-violet-600 dark:text-violet-400 mb-1 uppercase tracking-wide">Answer</p>
              <p className="text-sm text-zinc-700 dark:text-zinc-200 leading-relaxed whitespace-pre-wrap">{answerCard}</p>
            </div>
          )}

          {!isLoading && entries.length === 0 && !answerCard && (
            <div className="flex flex-col items-center justify-center h-32 text-zinc-400 dark:text-zinc-500">
              <Database size={32} className="mb-2 opacity-40" />
              <p className="text-xs">Search Nexus to find entries</p>
            </div>
          )}

          <div className="divide-y divide-zinc-100 dark:divide-zinc-800">
            {entries.map(entry => (
              <button
                key={entry.id}
                onClick={() => setSelectedEntry(entry)}
                className={`w-full text-left px-4 py-3 hover:bg-zinc-50 dark:hover:bg-zinc-800/50 transition-colors ${selectedEntry?.id === entry.id ? 'bg-indigo-50 dark:bg-indigo-950/30' : ''}`}
              >
                <div className="flex items-start justify-between gap-2 mb-1">
                  <p className="text-sm font-medium text-zinc-800 dark:text-zinc-100 line-clamp-1">{entry.title}</p>
                  <ChevronRight size={12} className="text-zinc-400 shrink-0 mt-0.5" />
                </div>
                <p className="text-xs text-zinc-500 dark:text-zinc-400 line-clamp-2 mb-1.5">{entry.content}</p>
                <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-medium ${categoryClass(entry.category)}`}>
                  {entry.category || 'general'}
                </span>
              </button>
            ))}
          </div>
        </div>

        {/* Entry detail */}
        <div className="flex-1 overflow-y-auto p-4">
          {selectedEntry ? (
            <div>
              <div className="flex items-start justify-between mb-3">
                <h2 className="text-base font-semibold text-zinc-800 dark:text-zinc-100 leading-tight">{selectedEntry.title}</h2>
                <button onClick={() => setSelectedEntry(null)} className="text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 ml-2 shrink-0">
                  <X size={14} />
                </button>
              </div>
              <div className="flex gap-2 mb-4 flex-wrap">
                <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${categoryClass(selectedEntry.category)}`}>
                  {selectedEntry.category || 'general'}
                </span>
                <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-zinc-100 dark:bg-zinc-800 text-zinc-500 dark:text-zinc-400">
                  {selectedEntry.content_type}
                </span>
                {selectedEntry.created_at && (
                  <span className="text-xs text-zinc-400 dark:text-zinc-500 self-center">
                    {new Date(selectedEntry.created_at).toLocaleDateString()}
                  </span>
                )}
              </div>
              <p className="text-sm text-zinc-700 dark:text-zinc-200 leading-relaxed whitespace-pre-wrap">{selectedEntry.content}</p>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center h-full text-zinc-400 dark:text-zinc-500">
              <Tag size={32} className="mb-2 opacity-40" />
              <p className="text-xs">Select an entry to view details</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
