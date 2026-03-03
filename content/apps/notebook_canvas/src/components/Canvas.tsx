import React, { useState } from 'react';
import { ViewMode, Source, Note, Workflow } from '../types';
import ChatCanvas from './ChatCanvas';
import NoteEditor from './NoteEditor';
import WorkflowBuilder from './WorkflowBuilder';
import SourceViewer from './SourceViewer';
import Browser from './Browser';
import DataTools from './DataTools';
import NexusPanel from './NexusPanel';
import NLMPanel from './NLMPanel';
import AiStudioPanel from './AiStudioPanel';
import AccountsPanel from './AccountsPanel';
import TrainingPanel from './TrainingPanel';
import { Send, Paperclip, Plus } from 'lucide-react';

interface Props {
  viewMode: ViewMode;
  activeItemId: string | null;
  activeNotebookId: string | null;
  sources: Source[];
  notes: Note[];
  workflows: Workflow[];
  lmStudioUrl: string;
  setNotes: React.Dispatch<React.SetStateAction<Note[]>>;
  setWorkflows: React.Dispatch<React.SetStateAction<Workflow[]>>;
  onAddSource: (title: string, content: string, type: 'text'|'url'|'file', url?: string) => void;
  onUpdateSource: (id: string, title: string, content: string) => void;
  onDeleteSource: (id: string) => void;
  isDarkMode: boolean;
  setActiveItemId: (id: string | null) => void;
  setViewMode: (mode: ViewMode) => void;
}

export default function Canvas({
  viewMode, activeItemId, activeNotebookId, sources, notes, workflows, lmStudioUrl, setNotes, setWorkflows, onAddSource, onUpdateSource, onDeleteSource, isDarkMode, setActiveItemId, setViewMode
}: Props) {
  const [promptText, setPromptText] = useState('');
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = React.useRef<HTMLInputElement>(null);

  if (!activeNotebookId) {
    return (
      <div className="flex-1 flex items-center justify-center bg-white dark:bg-zinc-900 text-zinc-400 dark:text-zinc-500 transition-colors">
        <p>Select or create a notebook to begin.</p>
      </div>
    );
  }

  const handlePromptSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!promptText.trim()) return;
    setPromptText('');
    setViewMode('chat');
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    
    // Try to get URL
    const url = e.dataTransfer.getData('text/uri-list') || e.dataTransfer.getData('text/plain');
    if (url && (url.startsWith('http://') || url.startsWith('https://'))) {
      onAddSource(url, `Source from ${url}`, 'url', url);
      return;
    }

    // Try to get text
    const text = e.dataTransfer.getData('text/plain');
    if (text) {
      onAddSource('Dropped Text', text, 'text');
    }
  };

  const handleAddFromClipboard = async () => {
    try {
      const text = await navigator.clipboard.readText();
      if (text) {
        if (text.startsWith('http://') || text.startsWith('https://')) {
          onAddSource(text, `Source from ${text}`, 'url', text);
        } else {
          onAddSource('Pasted Text', text, 'text');
        }
      }
    } catch (err) {
      console.error('Failed to read clipboard contents: ', err);
    }
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (event) => {
      const content = event.target?.result as string;
      onAddSource(file.name, content, 'text'); // Treating as text for simplicity
    };
    reader.readAsText(file);
  };

  const isSystemPanel = ['nexus', 'nlm', 'aistudio', 'accounts', 'training'].includes(viewMode);

  return (
    <div 
      className="flex-1 flex flex-col h-full bg-white dark:bg-zinc-900 relative overflow-hidden transition-colors"
      onDragOver={isSystemPanel ? undefined : handleDragOver}
      onDragLeave={isSystemPanel ? undefined : handleDragLeave}
      onDrop={isSystemPanel ? undefined : handleDrop}
    >
      {isDragging && !isSystemPanel && (
        <div className="absolute inset-0 z-50 bg-blue-500/20 border-4 border-blue-500 border-dashed flex items-center justify-center pointer-events-none">
          <div className="bg-white dark:bg-zinc-800 px-6 py-4 rounded-xl shadow-xl flex items-center gap-3">
            <Plus className="w-6 h-6 text-blue-500" />
            <span className="text-lg font-medium text-zinc-900 dark:text-zinc-100">Drop to add as source</span>
          </div>
        </div>
      )}
      {/* System Panels (full-canvas, no browser/prompt bar) */}
      {viewMode === 'nexus' && <NexusPanel />}
      {viewMode === 'nlm' && <NLMPanel />}
      {viewMode === 'aistudio' && <AiStudioPanel />}
      {viewMode === 'accounts' && <AccountsPanel />}
      {viewMode === 'training' && <TrainingPanel />}

      {/* Standard notebook panels */}
      {!isSystemPanel && (
        <>
      {/* Top Third: Browser */}
      <Browser onAddSource={onAddSource} />

      {/* Middle: Active View */}
      <div className="flex-1 relative overflow-hidden flex flex-col">
        {/* Workflow Tabs (if in workflow mode) */}
        {viewMode === 'workflow' && workflows.length > 0 && (
          <div className="flex items-center px-2 bg-zinc-100 dark:bg-zinc-800/50 border-b border-zinc-200 dark:border-zinc-800 shrink-0 h-8 overflow-x-auto">
            {workflows.map(w => (
              <button
                key={w.id}
                onClick={() => setActiveItemId(w.id)}
                className={`px-3 h-full text-xs font-medium border-r border-zinc-200 dark:border-zinc-800 transition-colors flex items-center ${
                  activeItemId === w.id 
                    ? 'bg-white dark:bg-zinc-900 text-blue-600 dark:text-blue-400 border-t-2 border-t-blue-500' 
                    : 'text-zinc-600 dark:text-zinc-400 hover:bg-zinc-200 dark:hover:bg-zinc-700 border-t-2 border-t-transparent'
                }`}
              >
                {w.name}
              </button>
            ))}
          </div>
        )}

        <div className="flex-1 relative overflow-hidden">
          {viewMode === 'chat' && (
            <ChatCanvas 
              lmStudioUrl={lmStudioUrl} 
              sources={sources} 
              onAddSource={onAddSource}
            />
          )}
          
          {viewMode === 'note' && activeItemId && (
            <NoteEditor 
              noteId={activeItemId} 
              notes={notes} 
              setNotes={setNotes} 
            />
          )}
          
          {viewMode === 'workflow' && activeItemId && (
            <WorkflowBuilder 
              workflowId={activeItemId} 
              workflows={workflows} 
              setWorkflows={setWorkflows} 
              sources={sources}
              lmStudioUrl={lmStudioUrl}
              activeNotebookId={activeNotebookId}
              onAddSource={onAddSource}
              onDeleteSource={onDeleteSource}
              setNotes={setNotes}
              isDarkMode={isDarkMode}
            />
          )}
          
          {viewMode === 'source' && activeItemId && (
            <SourceViewer 
              sourceId={activeItemId} 
              sources={sources} 
              onUpdateSource={onUpdateSource}
              onDeleteSource={onDeleteSource}
            />
          )}

          {viewMode === 'data' && (
            <DataTools />
          )}
        </div>
      </div>

      {/* Bottom: Universal Prompt */}
      <div className="shrink-0 p-3 bg-white dark:bg-zinc-900 border-t border-zinc-200 dark:border-zinc-800">
        <form onSubmit={handlePromptSubmit} className="flex items-end gap-2 max-w-4xl mx-auto">
          <button 
            type="button" 
            onClick={handleAddFromClipboard}
            title="Add from Clipboard"
            className="p-2 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300 transition-colors"
          >
            <Plus size={20} />
          </button>
          <input type="file" ref={fileInputRef} onChange={handleFileUpload} className="hidden" />
          <button 
            type="button" 
            onClick={() => fileInputRef.current?.click()}
            title="Upload File"
            className="p-2 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300 transition-colors"
          >
            <Paperclip size={20} />
          </button>
          <div className="flex-1 relative">
            <textarea
              value={promptText}
              onChange={e => setPromptText(e.target.value)}
              placeholder="Ask anything, add a file, or type a command..."
              className="w-full bg-zinc-100 dark:bg-zinc-800 border-none rounded-xl pl-4 pr-10 py-3 text-sm focus:ring-2 focus:ring-blue-500 dark:text-zinc-100 resize-none max-h-32"
              rows={1}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  handlePromptSubmit(e);
                }
              }}
            />
            <button 
              type="submit"
              disabled={!promptText.trim()}
              className="absolute right-2 bottom-2 p-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:hover:bg-blue-600 transition-colors"
            >
              <Send size={16} />
            </button>
          </div>
        </form>
      </div>
        </>
      )}
    </div>
  );
}
