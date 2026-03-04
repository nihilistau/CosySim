import React, { useState, useEffect, useRef } from 'react';
import { Send, BookOpen, Bot, User, Loader, AlertCircle } from 'lucide-react';

interface NLMNotebook {
  id: string;
  name: string;
  source_count?: number;
}

interface NLMMessage {
  role: 'user' | 'assistant';
  content: string;
  notebook_id?: string;
}

interface Props {
  activeNotebookId: string | null;
}

export default function NLMPanel({ activeNotebookId }: Props) {
  const [nlmNotebooks, setNlmNotebooks] = useState<NLMNotebook[]>([]);
  const [selectedNlmId, setSelectedNlmId] = useState<string | null>(null);
  const [messages, setMessages] = useState<NLMMessage[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const loadNotebooks = async () => {
      try {
        const res = await fetch('/api/nlm/notebooks');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const books: NLMNotebook[] = Array.isArray(data.notebooks)
          ? data.notebooks
          : Array.isArray(data)
          ? data
          : [];
        setNlmNotebooks(books);
        if (books.length > 0) setSelectedNlmId(books[0].id);
      } catch (e: any) {
        setLoadError(e.message);
      }
    };
    loadNotebooks();
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const selectedNotebook = nlmNotebooks.find(nb => nb.id === selectedNlmId);

  const handleSend = async () => {
    if (!input.trim() || isLoading) return;
    const userMsg: NLMMessage = { role: 'user', content: input, notebook_id: selectedNlmId ?? undefined };
    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setIsLoading(true);
    try {
      const res = await fetch('/api/nlm/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: input, notebook_id: selectedNlmId }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setMessages(prev => [...prev, { role: 'assistant', content: data.answer ?? JSON.stringify(data), notebook_id: selectedNlmId ?? undefined }]);
    } catch (e: any) {
      setMessages(prev => [...prev, { role: 'assistant', content: `Error: ${e.message}` }]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-full bg-white dark:bg-zinc-900 transition-colors">
      {/* Header */}
      <div className="h-14 border-b border-zinc-200 dark:border-zinc-800 flex items-center justify-between px-6 shrink-0 bg-zinc-50/50 dark:bg-zinc-900/50">
        <div className="flex items-center gap-2">
          <BookOpen size={16} className="text-purple-500" />
          <h1 className="text-sm font-bold tracking-widest text-zinc-700 dark:text-zinc-300 uppercase">NotebookLM</h1>
        </div>
        {selectedNotebook && (
          <span className="text-xs text-zinc-400 dark:text-zinc-500">
            {selectedNotebook.source_count != null ? `${selectedNotebook.source_count} sources` : ''}
          </span>
        )}
      </div>

      {/* Notebook picker */}
      <div className="px-4 py-3 border-b border-zinc-200 dark:border-zinc-800 shrink-0">
        {loadError ? (
          <div className="flex items-center gap-2 text-xs text-red-400">
            <AlertCircle size={13} />
            {loadError}
          </div>
        ) : nlmNotebooks.length === 0 ? (
          <div className="flex items-center gap-2 text-xs text-zinc-400 dark:text-zinc-500">
            <AlertCircle size={13} className="text-amber-500" />
            No notebooks — use the NLM panel to create one
          </div>
        ) : (
          <select
            value={selectedNlmId ?? ''}
            onChange={e => setSelectedNlmId(e.target.value || null)}
            className="w-full px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-purple-500 dark:text-zinc-200 transition-colors"
          >
            {nlmNotebooks.map(nb => (
              <option key={nb.id} value={nb.id}>{nb.name}{nb.source_count != null ? ` (${nb.source_count})` : ''}</option>
            ))}
          </select>
        )}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4 bg-zinc-50 dark:bg-zinc-950 transition-colors">
        {messages.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-zinc-400 dark:text-zinc-500">
            <BookOpen size={44} className="mb-3 opacity-40" />
            <p className="text-sm">Ask a question about your NotebookLM notebook.</p>
            {selectedNotebook && (
              <p className="text-xs mt-1 text-purple-400">Asking <span className="font-medium">{selectedNotebook.name}</span></p>
            )}
          </div>
        ) : (
          messages.map((m, i) => (
            <div key={i} className={`flex gap-3 ${m.role === 'user' ? 'flex-row-reverse' : ''}`}>
              <div className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 ${m.role === 'user' ? 'bg-zinc-700 dark:bg-zinc-600 text-white' : 'bg-purple-100 dark:bg-purple-900/50 text-purple-600 dark:text-purple-300'}`}>
                {m.role === 'user' ? <User size={14} /> : <Bot size={14} />}
              </div>
              <div className={`max-w-[80%] rounded-2xl px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap ${m.role === 'user' ? 'bg-zinc-100 dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100' : 'bg-white dark:bg-zinc-900 border border-purple-200 dark:border-purple-800 text-zinc-800 dark:text-zinc-200 shadow-sm'}`}>
                {m.content}
              </div>
            </div>
          ))
        )}
        {isLoading && (
          <div className="flex gap-3">
            <div className="w-7 h-7 rounded-full bg-purple-100 dark:bg-purple-900/50 text-purple-600 dark:text-purple-300 flex items-center justify-center shrink-0">
              <Bot size={14} />
            </div>
            <div className="bg-white dark:bg-zinc-900 border border-purple-200 dark:border-purple-800 rounded-2xl px-4 py-3 shadow-sm flex items-center gap-1.5">
              <div className="w-1.5 h-1.5 bg-purple-400 rounded-full animate-bounce" />
              <div className="w-1.5 h-1.5 bg-purple-400 rounded-full animate-bounce" style={{ animationDelay: '0.2s' }} />
              <div className="w-1.5 h-1.5 bg-purple-400 rounded-full animate-bounce" style={{ animationDelay: '0.4s' }} />
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="p-4 border-t border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shrink-0 transition-colors">
        <div className="relative">
          <textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); } }}
            placeholder={selectedNotebook ? `Ask ${selectedNotebook.name}...` : 'Select a notebook above...'}
            disabled={!selectedNlmId || nlmNotebooks.length === 0}
            rows={3}
            className="w-full bg-zinc-50 dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 rounded-xl pl-4 pr-12 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500 resize-none dark:text-zinc-200 disabled:opacity-50 transition-colors"
          />
          <button
            onClick={handleSend}
            disabled={isLoading || !input.trim() || !selectedNlmId}
            className="absolute right-3 bottom-3 p-2 bg-purple-600 hover:bg-purple-700 text-white rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {isLoading ? <Loader size={15} className="animate-spin" /> : <Send size={15} />}
          </button>
        </div>
      </div>
    </div>
  );
}
