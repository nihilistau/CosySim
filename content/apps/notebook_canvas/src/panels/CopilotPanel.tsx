/**
 * CopilotPanel — GitHub Copilot chat interface.
 *
 * Features:
 *   - Model selector populated from /api/copilot/models
 *   - Vendor badges (Anthropic=purple, OpenAI=green, Google=blue, xAI=orange)
 *   - Multi-turn chat using Copilot threads
 *   - Thread history sidebar
 *   - Dark glass theme matching other panels
 */

import React, { useState, useEffect, useRef } from 'react';
import {
  Send, RefreshCw, Plus, MessageSquare, Loader, Bot, User,
  Github, ChevronDown, Trash2,
} from 'lucide-react';

// ── Types ─────────────────────────────────────────────────────────────────────

interface CopilotModel {
  id: string;
  vendor?: string;
  company?: string;
  name?: string;
}

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  model?: string;
  timestamp: number;
}

interface ThreadEntry {
  id: string;
  label: string;
  messages: ChatMessage[];
  created_at: number;
  last_message_id: string;
}

// ── Vendor badge ──────────────────────────────────────────────────────────────

function vendorFromModel(model: CopilotModel): string {
  const v = (model.vendor || model.company || '').toLowerCase();
  const id = (model.id || '').toLowerCase();
  if (v.includes('anthropic') || id.includes('claude')) return 'Anthropic';
  if (v.includes('openai') || id.includes('gpt') || id.includes('codex')) return 'OpenAI';
  if (v.includes('google') || id.includes('gemini') || id.includes('gemma')) return 'Google';
  if (v.includes('xai') || id.includes('grok')) return 'xAI';
  return v || 'Other';
}

function VendorBadge({ vendor }: { vendor: string }) {
  const cls: Record<string, string> = {
    Anthropic: 'bg-purple-900/60 text-purple-300 border-purple-700/50',
    OpenAI:    'bg-green-900/60  text-green-300  border-green-700/50',
    Google:    'bg-blue-900/60   text-blue-300   border-blue-700/50',
    xAI:       'bg-orange-900/60 text-orange-300 border-orange-700/50',
    Other:     'bg-zinc-700/60   text-zinc-300   border-zinc-600/50',
  };
  const color = cls[vendor] || cls.Other;
  return (
    <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold uppercase border ${color}`}>
      {vendor}
    </span>
  );
}

// ── Model selector ────────────────────────────────────────────────────────────

function ModelSelector({
  models, selected, onSelect,
}: {
  models: CopilotModel[];
  selected: string;
  onSelect: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const current = models.find(m => m.id === selected);
  const vendor = current ? vendorFromModel(current) : '';

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(v => !v)}
        className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-zinc-800/80 border border-zinc-700/50 hover:border-zinc-500 text-sm text-zinc-200 transition-colors min-w-[220px] max-w-[320px]"
      >
        {vendor && <VendorBadge vendor={vendor} />}
        <span className="flex-1 truncate text-left">{selected || 'Select model'}</span>
        <ChevronDown size={14} className="text-zinc-400 shrink-0" />
      </button>

      {open && (
        <div className="absolute top-full left-0 mt-1 w-72 bg-zinc-900 border border-zinc-700 rounded-xl shadow-2xl z-50 max-h-80 overflow-y-auto">
          {models.length === 0 && (
            <div className="px-3 py-2 text-xs text-zinc-500">No models loaded</div>
          )}
          {models.map(m => {
            const v = vendorFromModel(m);
            return (
              <button
                key={m.id}
                onClick={() => { onSelect(m.id); setOpen(false); }}
                className={`flex items-center gap-2 w-full px-3 py-2 text-left text-xs transition-colors hover:bg-zinc-800 ${
                  m.id === selected ? 'bg-zinc-800 text-white' : 'text-zinc-300'
                }`}
              >
                <VendorBadge vendor={v} />
                <span className="truncate">{m.id}</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Message bubble ────────────────────────────────────────────────────────────

function MessageBubble({ msg }: { msg: ChatMessage }) {
  const isUser = msg.role === 'user';
  return (
    <div className={`flex gap-2 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
      <div className={`w-6 h-6 rounded-full flex items-center justify-center shrink-0 mt-0.5 ${
        isUser ? 'bg-blue-600' : 'bg-purple-700'
      }`}>
        {isUser ? <User size={12} className="text-white" /> : <Bot size={12} className="text-white" />}
      </div>
      <div className={`max-w-[85%] rounded-xl px-3 py-2 text-sm leading-relaxed whitespace-pre-wrap break-words ${
        isUser
          ? 'bg-blue-600/20 border border-blue-500/30 text-blue-100'
          : 'bg-zinc-800/80 border border-zinc-700/50 text-zinc-100'
      }`}>
        {msg.content}
        {msg.model && (
          <div className="mt-1 text-[10px] text-zinc-500">{msg.model}</div>
        )}
      </div>
    </div>
  );
}

// ── Main panel ────────────────────────────────────────────────────────────────

export default function CopilotPanel() {
  const [models, setModels] = useState<CopilotModel[]>([]);
  const [selectedModel, setSelectedModel] = useState('claude-sonnet-4.6');
  const [modelsError, setModelsError] = useState<string | null>(null);
  const [threads, setThreads] = useState<ThreadEntry[]>([]);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [accountName] = useState('nihilistcod');
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const activeThread = threads.find(t => t.id === activeThreadId) ?? null;
  const messages = activeThread?.messages ?? [];

  // Load models on mount
  useEffect(() => {
    fetch('/api/copilot/models')
      .then(r => r.json())
      .then((data: CopilotModel[] | { error?: string }) => {
        if (Array.isArray(data)) {
          setModels(data);
          if (data.length > 0 && !data.find(m => m.id === selectedModel)) {
            setSelectedModel(data[0].id);
          }
        } else if ((data as any).error) {
          setModelsError((data as any).error);
        }
      })
      .catch(e => setModelsError(e.message));
  }, []);

  // Scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const createNewThread = () => {
    const id = `local-${Date.now()}`;
    const thread: ThreadEntry = {
      id,
      label: `Thread ${threads.length + 1}`,
      messages: [],
      created_at: Date.now(),
      last_message_id: 'root',
    };
    setThreads(prev => [thread, ...prev]);
    setActiveThreadId(id);
  };

  const handleSend = async () => {
    const text = input.trim();
    if (!text || isLoading) return;

    // Ensure we have a thread
    let currentThreadId = activeThreadId;
    let currentThread = threads.find(t => t.id === activeThreadId);

    if (!currentThread) {
      // Create thread on server
      try {
        const resp = await fetch('/api/copilot/thread/create', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ account_name: accountName }),
        });
        const data = await resp.json();
        if (data.error) throw new Error(data.error);

        const newThread: ThreadEntry = {
          id: data.thread_id,
          label: text.slice(0, 40),
          messages: [],
          created_at: Date.now(),
          last_message_id: 'root',
        };
        setThreads(prev => [newThread, ...prev]);
        setActiveThreadId(data.thread_id);
        currentThreadId = data.thread_id;
        currentThread = newThread;
      } catch (e: any) {
        setModelsError(`Thread creation failed: ${e.message}`);
        return;
      }
    }

    const userMsg: ChatMessage = { role: 'user', content: text, timestamp: Date.now() };
    setInput('');
    setIsLoading(true);

    // Optimistically add user message
    setThreads(prev => prev.map(t => t.id === currentThreadId
      ? { ...t, messages: [...t.messages, userMsg], label: t.messages.length === 0 ? text.slice(0, 40) : t.label }
      : t
    ));

    try {
      const parentMsgId = currentThread?.last_message_id ?? 'root';
      const resp = await fetch(`/api/copilot/thread/${currentThreadId}/message`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          content: text,
          model: selectedModel,
          parent_message_id: parentMsgId,
          account_name: accountName,
        }),
      });
      const data = await resp.json();

      if (data.error) throw new Error(data.error);

      const assistantMsg: ChatMessage = {
        role: 'assistant',
        content: data.response || '(no response)',
        model: data.model,
        timestamp: Date.now(),
      };
      const newMsgId = data.message_id || 'root';

      setThreads(prev => prev.map(t => t.id === currentThreadId
        ? { ...t, messages: [...t.messages, assistantMsg], last_message_id: newMsgId }
        : t
      ));
    } catch (e: any) {
      const errMsg: ChatMessage = {
        role: 'assistant',
        content: `Error: ${e.message}`,
        timestamp: Date.now(),
      };
      setThreads(prev => prev.map(t => t.id === currentThreadId
        ? { ...t, messages: [...t.messages, errMsg] }
        : t
      ));
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const deleteThread = (id: string) => {
    setThreads(prev => prev.filter(t => t.id !== id));
    if (activeThreadId === id) setActiveThreadId(null);
  };

  return (
    <div className="flex h-full bg-zinc-950 text-zinc-100 overflow-hidden">
      {/* Thread sidebar */}
      <div className="w-52 shrink-0 border-r border-zinc-800 flex flex-col bg-zinc-900/50">
        <div className="p-2 border-b border-zinc-800 flex items-center justify-between">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-zinc-400 uppercase tracking-wider">
            <Github size={12} />
            Threads
          </div>
          <button
            onClick={createNewThread}
            className="p-1 rounded hover:bg-zinc-700 text-zinc-400 hover:text-zinc-200 transition-colors"
            title="New thread"
          >
            <Plus size={12} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-1 space-y-0.5">
          {threads.length === 0 && (
            <p className="text-[11px] text-zinc-600 px-2 py-3 text-center">
              No threads yet.<br />Send a message to start.
            </p>
          )}
          {threads.map(t => (
            <div
              key={t.id}
              className={`group flex items-center gap-1 px-2 py-1.5 rounded-lg cursor-pointer transition-colors ${
                t.id === activeThreadId
                  ? 'bg-purple-900/40 border border-purple-700/40 text-purple-200'
                  : 'hover:bg-zinc-800 text-zinc-400 hover:text-zinc-200'
              }`}
              onClick={() => setActiveThreadId(t.id)}
            >
              <MessageSquare size={11} className="shrink-0" />
              <span className="flex-1 truncate text-[11px]">{t.label || 'New thread'}</span>
              <button
                onClick={e => { e.stopPropagation(); deleteThread(t.id); }}
                className="opacity-0 group-hover:opacity-100 p-0.5 rounded hover:text-red-400 transition-all"
              >
                <Trash2 size={10} />
              </button>
            </div>
          ))}
        </div>
        <div className="p-2 border-t border-zinc-800">
          <div className="text-[10px] text-zinc-600">
            Account: <span className="text-zinc-400">{accountName}</span>
          </div>
        </div>
      </div>

      {/* Main chat area */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Header bar */}
        <div className="shrink-0 px-4 py-2 border-b border-zinc-800 bg-zinc-900/50 flex items-center gap-3">
          <Github size={16} className="text-white" />
          <span className="text-sm font-semibold text-zinc-200">GitHub Copilot</span>
          <div className="flex-1" />
          <ModelSelector models={models} selected={selectedModel} onSelect={setSelectedModel} />
          {modelsError && (
            <span className="text-[10px] text-red-400 max-w-[160px] truncate" title={modelsError}>
              ⚠ {modelsError}
            </span>
          )}
          <button
            onClick={() => {
              setModelsError(null);
              fetch('/api/copilot/models')
                .then(r => r.json())
                .then((data: CopilotModel[]) => { if (Array.isArray(data)) setModels(data); })
                .catch(e => setModelsError(e.message));
            }}
            className="p-1.5 rounded hover:bg-zinc-700 text-zinc-400 hover:text-zinc-200 transition-colors"
            title="Refresh models"
          >
            <RefreshCw size={13} />
          </button>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
          {!activeThreadId && (
            <div className="flex flex-col items-center justify-center h-full text-center text-zinc-500">
              <Github size={40} className="mb-3 text-zinc-700" />
              <p className="text-sm font-medium text-zinc-400">GitHub Copilot</p>
              <p className="text-xs mt-1 mb-4 max-w-xs">
                {models.length > 0
                  ? `${models.length} models available — type a message to start`
                  : 'Loading models…'}
              </p>
              {models.length > 0 && (
                <div className="flex flex-wrap gap-1.5 justify-center max-w-xs">
                  {['Anthropic', 'OpenAI', 'Google', 'xAI'].map(v => (
                    <VendorBadge key={v} vendor={v} />
                  ))}
                </div>
              )}
            </div>
          )}
          {messages.map((msg, i) => (
            <MessageBubble key={i} msg={msg} />
          ))}
          {isLoading && (
            <div className="flex gap-2">
              <div className="w-6 h-6 rounded-full bg-purple-700 flex items-center justify-center shrink-0 mt-0.5">
                <Bot size={12} className="text-white" />
              </div>
              <div className="px-3 py-2 bg-zinc-800/80 border border-zinc-700/50 rounded-xl">
                <Loader size={14} className="text-purple-400 animate-spin" />
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Input bar */}
        <div className="shrink-0 px-4 py-3 border-t border-zinc-800 bg-zinc-900/50">
          <div className="flex gap-2 items-end">
            <textarea
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Message Copilot… (Enter to send, Shift+Enter for newline)"
              rows={1}
              className="flex-1 resize-none px-3 py-2 rounded-xl bg-zinc-800 border border-zinc-700 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-purple-500/60 transition-colors max-h-32 min-h-[40px]"
              style={{ height: 'auto' }}
              onInput={e => {
                const el = e.currentTarget;
                el.style.height = 'auto';
                el.style.height = `${Math.min(el.scrollHeight, 128)}px`;
              }}
            />
            <button
              onClick={handleSend}
              disabled={!input.trim() || isLoading}
              className="p-2.5 rounded-xl bg-purple-700 hover:bg-purple-600 disabled:opacity-40 disabled:cursor-not-allowed text-white transition-colors shrink-0"
            >
              {isLoading ? <Loader size={16} className="animate-spin" /> : <Send size={16} />}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
