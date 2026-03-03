import React, { useState, useRef } from 'react';
import { Globe, RefreshCw, Plus, Copy, FileText, ChevronUp, ChevronDown } from 'lucide-react';
import TurndownService from 'turndown';

interface Props {
  onAddSource: (title: string, content: string, type: 'text'|'url'|'file', url?: string) => void;
}

export default function Browser({ onAddSource }: Props) {
  const [url, setUrl] = useState('https://en.wikipedia.org/wiki/Main_Page');
  const [inputUrl, setInputUrl] = useState(url);
  const [isConverting, setIsConverting] = useState(false);
  const [isCollapsed, setIsCollapsed] = useState(false);
  const iframeRef = useRef<HTMLIFrameElement>(null);

  const handleGo = (e: React.FormEvent) => {
    e.preventDefault();
    let finalUrl = inputUrl;
    if (!finalUrl.startsWith('http://') && !finalUrl.startsWith('https://')) {
      finalUrl = 'https://' + finalUrl;
    }
    setUrl(finalUrl);
    setInputUrl(finalUrl);
  };

  const handleAddAsSource = () => {
    onAddSource(url, `Source from ${url}`, 'url', url);
  };

  const handleCopyUrl = () => {
    navigator.clipboard.writeText(url);
  };

  const handlePasteUrl = async () => {
    try {
      const text = await navigator.clipboard.readText();
      if (text) {
        setInputUrl(text);
        setUrl(text);
      }
    } catch (err) {
      console.error('Failed to read clipboard contents: ', err);
    }
  };

  const handleConvertToMarkdown = async () => {
    setIsConverting(true);
    try {
      const res = await fetch('/api/fetch-url', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url })
      });
      const data = await res.json();
      if (data.text) {
        const turndownService = new TurndownService();
        const markdown = turndownService.turndown(data.text);
        onAddSource(url, markdown, 'text', url);
      }
    } catch (err) {
      console.error('Failed to convert to markdown:', err);
    } finally {
      setIsConverting(false);
    }
  };

  return (
    <div className={`flex flex-col border-b border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 transition-all duration-300 ${isCollapsed ? 'h-10' : 'h-1/3 min-h-[250px]'}`}>
      <div className="flex items-center p-2 border-b border-zinc-200 dark:border-zinc-800 gap-2 bg-zinc-50 dark:bg-zinc-950 transition-colors h-10 shrink-0">
        <button onClick={() => setIsCollapsed(!isCollapsed)} className="p-1 hover:bg-zinc-200 dark:hover:bg-zinc-800 rounded text-zinc-500 transition-colors">
          {isCollapsed ? <ChevronDown className="w-4 h-4" /> : <ChevronUp className="w-4 h-4" />}
        </button>
        <Globe className="w-4 h-4 text-zinc-500" />
        <form onSubmit={handleGo} className="flex-1 flex">
          <input 
            type="text" 
            value={inputUrl}
            onChange={e => setInputUrl(e.target.value)}
            className="flex-1 bg-white dark:bg-zinc-900 border border-zinc-300 dark:border-zinc-700 rounded px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500 text-zinc-900 dark:text-zinc-100 transition-colors"
            placeholder="Enter URL..."
          />
        </form>
        <button onClick={handlePasteUrl} title="Paste from Clipboard" className="p-1 hover:bg-zinc-200 dark:hover:bg-zinc-800 rounded text-zinc-500 transition-colors">
          <Copy className="w-4 h-4" />
        </button>
        <button onClick={() => setUrl(url)} title="Refresh" className="p-1 hover:bg-zinc-200 dark:hover:bg-zinc-800 rounded text-zinc-500 transition-colors">
          <RefreshCw className="w-4 h-4" />
        </button>
        <button onClick={handleAddAsSource} title="Add URL to Sources" className="p-1 hover:bg-zinc-200 dark:hover:bg-zinc-800 rounded text-zinc-500 transition-colors">
          <Plus className="w-4 h-4" />
        </button>
        <button 
          onClick={handleConvertToMarkdown} 
          disabled={isConverting}
          title="Convert Page to Markdown Source" 
          className="p-1 hover:bg-zinc-200 dark:hover:bg-zinc-800 rounded text-zinc-500 transition-colors disabled:opacity-50"
        >
          <FileText className="w-4 h-4" />
        </button>
      </div>
      {!isCollapsed && (
        <div className="flex-1 relative bg-white dark:bg-zinc-900">
          <iframe 
            ref={iframeRef}
            src={url} 
            className="w-full h-full border-none"
            sandbox="allow-same-origin allow-scripts allow-popups allow-forms"
          />
        </div>
      )}
    </div>
  );
}
