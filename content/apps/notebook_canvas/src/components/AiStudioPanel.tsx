import React, { useState, useEffect, useRef } from 'react';
import { Send, Zap, Bot, User, Loader, Settings, Info } from 'lucide-react';

interface AIModel {
  id: string;
  name: string;
  description?: string;
  context_window?: number;
}

interface Message {
  role: 'user' | 'assistant';
  content: string;
  model?: string;
}

interface Props {
  activeNotebookId: string | null;
  sources: Array<{ id: string; title: string; content: string }>;
}

export default function AiStudioPanel({ activeNotebookId, sources }: Props) {
  const [models, setModels] = useState<AIModel[]>([]);
  const [selectedModel, setSelectedModel] = useState('gemini-2.0-flash');
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [temperature, setTemperature] = useState(0.7);
  const [includeSourcesInContext, setIncludeSourcesInContext] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [modelsError, setModelsError] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const loadModels = async () => {
      try {
        const res = await fetch('/api/aistudio/models');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const list: AIModel[] = data.models ?? data ?? [];
        setModels(list);
        if (list.length > 0) setSelectedModel(list[0].id);
      } catch (e: any) {
        setModelsError(e.message);
      }
    };
    loadModels();
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = async () => {
    if (!input.trim() || isLoading) return;

    let prompt = input;
    if (includeSourcesInContext && sources.length > 0) {
      const ctx = sources.map(s => `### ${s.title}\n${s.content}`).join('\n\n');
      prompt = `Context from notebook sources:\n\n${ctx}\n\n---\n\n${input}`;
    }

    const userMsg: Message = { role: 'user', content: input };
    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setIsLoading(true);

    try {
      const res = await fetch('/api/aistudio/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt, model: selectedModel, temperature, max_tokens: 2048 }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: data.text ?? data.content ?? data.response ?? JSON.stringify(data),
        model: selectedModel,
      }]);
    } catch (e: any) {
      setMessages(prev => [...prev, { role: 'assistant', content: `Error: ${e.message}`, model: selectedModel }]);
    } finally {
      setIsLoading(false);
    }
  };

  const modelLabel = models.find(m => m.id === selectedModel)?.name ?? selectedModel;

  return (
    <div className="flex flex-col h-full bg-white dark:bg-zinc-900 transition-colors">
      {/* Header */}
      <div className="h-14 border-b border-zinc-200 dark:border-zinc-800 flex items-center justify-between px-6 shrink-0 bg-zinc-50/50 dark:bg-zinc-900/50">
        <div className="flex items-center gap-2">
          <Zap size={16} className="text-blue-500" />
          <h1 className="text-sm font-bold tracking-widest text-zinc-700 dark:text-zinc-300 uppercase">AI Studio</h1>
        </div>
        <div className="flex items-center gap-2">
          {models.length > 0 ? (
            <select
              value={selectedModel}
              onChange={e => setSelectedModel(e.target.value)}
              className="text-xs px-2 py-1.5 bg-zinc-100 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 dark:text-zinc-200"
            >
              {models.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
            </select>
          ) : (
            <span className="text-xs text-zinc-400 dark:text-zinc-500">
              {modelsError ? 'No accounts (add HAR)' : `${models.length} models available`}
            </span>
          )}
          <button
            onClick={() => setShowSettings(v => !v)}
            className={`p-1.5 rounded-lg transition-colors ${showSettings ? 'bg-blue-100 dark:bg-blue-900/40 text-blue-600 dark:text-blue-400' : 'text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800'}`}
          >
            <Settings size={15} />
          </button>
        </div>
      </div>

      {/* Settings bar */}
      {showSettings && (
        <div className="px-6 py-3 border-b border-zinc-200 dark:border-zinc-800 bg-blue-50/50 dark:bg-blue-950/20 shrink-0 flex items-center gap-6 flex-wrap">
          <div className="flex items-center gap-3">
            <label className="text-xs text-zinc-600 dark:text-zinc-400 font-medium whitespace-nowrap">Temperature</label>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={temperature}
              onChange={e => setTemperature(parseFloat(e.target.value))}
              className="w-28 accent-blue-500"
            />
            <span className="text-xs font-mono text-zinc-500 dark:text-zinc-400 w-8">{temperature.toFixed(2)}</span>
          </div>
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={includeSourcesInContext}
              onChange={e => setIncludeSourcesInContext(e.target.checked)}
              className="rounded accent-blue-500"
            />
            <span className="text-xs text-zinc-600 dark:text-zinc-400">Use notebook sources ({sources.length})</span>
          </label>
          {models.length === 0 && (
            <div className="flex items-center gap-1.5 text-xs text-amber-600 dark:text-amber-400 ml-auto">
              <Info size={12} />
              No accounts — import a HAR file in Accounts panel
            </div>
          )}
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4 bg-zinc-50 dark:bg-zinc-950 transition-colors">
        {messages.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-zinc-400 dark:text-zinc-500">
            <Zap size={44} className="mb-3 opacity-40 text-blue-400" />
            <p className="text-sm">Generate with Google AI.</p>
            <p className="text-xs mt-1">{models.length > 0 ? `${models.length} model${models.length !== 1 ? 's' : ''} available` : modelsError ? 'No accounts — add HAR file to unlock' : 'Loading models...'}</p>
          </div>
        ) : (
          messages.map((m, i) => (
            <div key={i} className={`flex gap-3 ${m.role === 'user' ? 'flex-row-reverse' : ''}`}>
              <div className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 ${m.role === 'user' ? 'bg-zinc-700 dark:bg-zinc-600 text-white' : 'bg-blue-100 dark:bg-blue-900/50 text-blue-600 dark:text-blue-300'}`}>
                {m.role === 'user' ? <User size={14} /> : <Bot size={14} />}
              </div>
              <div className={`max-w-[80%] ${m.role === 'user' ? 'items-end' : 'items-start'} flex flex-col gap-1`}>
                {m.role === 'assistant' && m.model && (
                  <span className="text-[10px] text-blue-500 dark:text-blue-400 font-medium px-1">{m.model}</span>
                )}
                <div className={`rounded-2xl px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap ${m.role === 'user' ? 'bg-zinc-100 dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100' : 'bg-blue-50 dark:bg-blue-950/40 border border-blue-200 dark:border-blue-800 text-zinc-800 dark:text-zinc-200 shadow-sm'}`}>
                  {m.content}
                </div>
              </div>
            </div>
          ))
        )}
        {isLoading && (
          <div className="flex gap-3">
            <div className="w-7 h-7 rounded-full bg-blue-100 dark:bg-blue-900/50 text-blue-600 dark:text-blue-300 flex items-center justify-center shrink-0">
              <Bot size={14} />
            </div>
            <div className="bg-blue-50 dark:bg-blue-950/40 border border-blue-200 dark:border-blue-800 rounded-2xl px-4 py-3 shadow-sm flex items-center gap-1.5">
              <div className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce" />
              <div className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: '0.2s' }} />
              <div className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: '0.4s' }} />
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
            placeholder="Generate with AI Studio..."
            rows={3}
            className="w-full bg-zinc-50 dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 rounded-xl pl-4 pr-12 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none dark:text-zinc-200 transition-colors"
          />
          <button
            onClick={handleSend}
            disabled={isLoading || !input.trim()}
            className="absolute right-3 bottom-3 p-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-1"
          >
            {isLoading ? <Loader size={15} className="animate-spin" /> : <Zap size={15} />}
          </button>
        </div>
        <p className="mt-1.5 text-[10px] text-zinc-400 dark:text-zinc-500 text-right">
          Model: {modelLabel} · Temp: {temperature}
          {includeSourcesInContext && ` · ${sources.length} sources in context`}
        </p>
      </div>
    </div>
  );
}
