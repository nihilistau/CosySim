import React, { useState, useRef, useEffect } from 'react';
import { Source } from '../types';
import { Send, Bot, User, BookmarkPlus, ThumbsUp, ThumbsDown, ChevronDown } from 'lucide-react';

type Backend = 'lmstudio' | 'nlm' | 'aistudio';

interface Props {
  lmStudioUrl: string;
  sources: Source[];
  onAddSource: (title: string, content: string, type: 'text'|'url'|'file', url?: string) => void;
}

interface Message {
  role: 'user' | 'assistant' | 'system';
  content: string;
  rating?: 'positive' | 'negative' | null;
}

export default function ChatCanvas({ lmStudioUrl, sources, onAddSource }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [backend, setBackend] = useState<Backend>('lmstudio');
  const [backendMenuOpen, setBackendMenuOpen] = useState(false);
  const [lmModel, setLmModel] = useState<string>('');

  useEffect(() => {
    fetch('/api/lmstudio/models')
      .then(r => r.json())
      .then(d => { if (Array.isArray(d.models) && d.models.length > 0) setLmModel(d.models[0].id || d.models[0].key || ''); })
      .catch(() => {});
  }, []);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const BACKEND_LABELS: Record<Backend, string> = {
    lmstudio: 'LMStudio',
    nlm: 'NotebookLM',
    aistudio: 'AI Studio',
  };

  const captureTrainingExample = async (prompt: string, response: string, rating: 'positive' | 'negative') => {
    try {
      await fetch('/api/training/capture', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt, response, rating, source: `chat_canvas_${backend}` }),
      });
    } catch { /* non-blocking */ }
  };

  const rateMessage = (msgIndex: number, rating: 'positive' | 'negative') => {
    setMessages(prev => {
      const updated = prev.map((m, i) => i === msgIndex ? { ...m, rating } : m);
      // Find the preceding user message for training capture
      const assistantMsg = updated[msgIndex];
      const userMsg = updated.slice(0, msgIndex).reverse().find(m => m.role === 'user');
      if (userMsg && assistantMsg.role === 'assistant') {
        captureTrainingExample(userMsg.content, assistantMsg.content, rating);
      }
      return updated;
    });
  };

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = async () => {
    if (!input.trim()) return;
    
    const userMsg: Message = { role: 'user', content: input };
    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setIsLoading(true);

    const contextStr = sources.map(s => `Source: ${s.title}\n${s.content}`).join('\n\n');
    const systemPrompt = `You are an AI assistant. Use the following sources to answer the user's questions if relevant:\n\n${contextStr}`;

    try {
      let responseContent = '';

      if (backend === 'lmstudio') {
        const res = await fetch('/api/lmstudio/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            model: lmModel || undefined,
            messages: messages.map(m => ({ role: m.role, content: m.content })),
            system: systemPrompt,
            temperature: 0.7,
          }),
        });
        if (!res.ok) throw new Error('LMStudio API error');
        const data = await res.json();
        responseContent = data.text ?? data.choices?.[0]?.message?.content ?? '';

      } else if (backend === 'aistudio') {
        const res = await fetch('/api/aistudio/generate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ prompt: userMsg.content, context: contextStr }),
        });
        if (!res.ok) throw new Error('AI Studio error');
        const data = await res.json();
        responseContent = data.text || data.content || JSON.stringify(data);

      } else if (backend === 'nlm') {
        const res = await fetch('/api/nlm/ask', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ question: userMsg.content }),
        });
        if (!res.ok) throw new Error('NLM error');
        const data = await res.json();
        responseContent = data.answer || data.text || JSON.stringify(data);
      }

      setMessages(prev => [...prev, { role: 'assistant', content: responseContent }]);
    } catch (err) {
      console.error(err);
      const label = BACKEND_LABELS[backend];
      setMessages(prev => [...prev, { role: 'assistant', content: `Error: Could not connect to ${label}. Check that it is running and configured correctly.` }]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSaveAsSource = () => {
    const content = messages.map(m => `${m.role.toUpperCase()}: ${m.content}`).join('\n\n');
    onAddSource(`Chat History - ${new Date().toLocaleString()}`, content, 'text');
  };

  return (
    <div className="flex flex-col h-full bg-white dark:bg-zinc-900 relative transition-colors">
      {/* Header */}
      <div className="h-14 border-b border-zinc-200 dark:border-zinc-800 flex items-center justify-between px-6 shrink-0 bg-zinc-50/50 dark:bg-zinc-900/50 transition-colors">
        <div className="flex items-center gap-3">
          <h1 className="text-lg font-semibold text-zinc-800 dark:text-zinc-200">Agent Canvas</h1>
          {/* Backend selector */}
          <div className="relative">
            <button
              onClick={() => setBackendMenuOpen(v => !v)}
              className="flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium bg-zinc-100 dark:bg-zinc-800 hover:bg-zinc-200 dark:hover:bg-zinc-700 rounded border border-zinc-300 dark:border-zinc-700 transition-colors"
            >
              {BACKEND_LABELS[backend]}
              <ChevronDown size={12} />
            </button>
            {backendMenuOpen && (
              <div className="absolute top-full left-0 mt-1 w-32 bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded shadow-lg z-20">
                {(Object.keys(BACKEND_LABELS) as Backend[]).map(b => (
                  <button
                    key={b}
                    onClick={() => { setBackend(b); setBackendMenuOpen(false); }}
                    className={`w-full text-left px-3 py-2 text-xs hover:bg-zinc-100 dark:hover:bg-zinc-700 transition-colors ${b === backend ? 'font-semibold text-blue-600 dark:text-blue-400' : 'text-zinc-700 dark:text-zinc-300'}`}
                  >
                    {BACKEND_LABELS[b]}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
        <button 
          onClick={handleSaveAsSource}
          className="flex items-center gap-2 text-xs font-medium text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-200 bg-zinc-100 dark:bg-zinc-800 hover:bg-zinc-200 dark:hover:bg-zinc-700 px-3 py-1.5 rounded transition-colors"
        >
          <BookmarkPlus size={14} />
          Save Chat as Source
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-6 space-y-6 bg-zinc-50 dark:bg-zinc-950 transition-colors">
        {messages.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-zinc-400 dark:text-zinc-500">
            <Bot size={48} className="mb-4 opacity-50" />
            <p>Start a conversation with your local agent.</p>
            <p className="text-sm mt-2">It has access to {sources.length} sources in this notebook.</p>
          </div>
        ) : (
          messages.map((m, i) => (
            <div key={i} className={`flex gap-4 ${m.role === 'user' ? 'flex-row-reverse' : ''}`}>
              <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 ${m.role === 'user' ? 'bg-zinc-800 dark:bg-zinc-700 text-white' : 'bg-emerald-100 dark:bg-emerald-900/50 text-emerald-700 dark:text-emerald-400'}`}>
                {m.role === 'user' ? <User size={16} /> : <Bot size={16} />}
              </div>
              <div className={`max-w-[80%] flex flex-col gap-1 ${m.role === 'user' ? 'items-end' : 'items-start'}`}>
                <div className={`rounded-2xl px-4 py-3 ${m.role === 'user' ? 'bg-zinc-100 dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100' : 'bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 text-zinc-800 dark:text-zinc-200 shadow-sm'}`}>
                  <p className="whitespace-pre-wrap text-sm leading-relaxed">{m.content}</p>
                </div>
                {m.role === 'assistant' && (
                  <div className="flex gap-1 px-1">
                    <button
                      onClick={() => rateMessage(i, 'positive')}
                      className={`p-1 rounded transition-colors ${m.rating === 'positive' ? 'text-emerald-500 bg-emerald-50 dark:bg-emerald-900/30' : 'text-zinc-400 hover:text-emerald-500 dark:hover:text-emerald-400'}`}
                      title="Good response"
                    >
                      <ThumbsUp size={13} />
                    </button>
                    <button
                      onClick={() => rateMessage(i, 'negative')}
                      className={`p-1 rounded transition-colors ${m.rating === 'negative' ? 'text-red-500 bg-red-50 dark:bg-red-900/30' : 'text-zinc-400 hover:text-red-500 dark:hover:text-red-400'}`}
                      title="Bad response"
                    >
                      <ThumbsDown size={13} />
                    </button>
                  </div>
                )}
              </div>
            </div>
          ))
        )}
        {isLoading && (
          <div className="flex gap-4">
            <div className="w-8 h-8 rounded-full bg-emerald-100 dark:bg-emerald-900/50 text-emerald-700 dark:text-emerald-400 flex items-center justify-center shrink-0">
              <Bot size={16} />
            </div>
            <div className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-2xl px-4 py-3 shadow-sm flex items-center gap-2">
              <div className="w-2 h-2 bg-zinc-300 dark:bg-zinc-600 rounded-full animate-bounce" />
              <div className="w-2 h-2 bg-zinc-300 dark:bg-zinc-600 rounded-full animate-bounce" style={{ animationDelay: '0.2s' }} />
              <div className="w-2 h-2 bg-zinc-300 dark:bg-zinc-600 rounded-full animate-bounce" style={{ animationDelay: '0.4s' }} />
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="p-4 border-t border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shrink-0 transition-colors">
        <div className="max-w-4xl mx-auto relative">
          <textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            placeholder="Ask about your sources or manipulate data..."
            className="w-full bg-zinc-50 dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 rounded-xl pl-4 pr-12 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-zinc-800 dark:focus:ring-zinc-600 focus:border-transparent resize-none h-24 dark:text-zinc-200 transition-colors"
          />
          <button 
            onClick={handleSend}
            disabled={isLoading || !input.trim()}
            className="absolute right-3 bottom-3 p-2 bg-zinc-800 dark:bg-zinc-700 text-white rounded-lg hover:bg-zinc-700 dark:hover:bg-zinc-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            <Send size={16} />
          </button>
        </div>
      </div>
    </div>
  );
}
