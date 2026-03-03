import React, { useState, useEffect } from 'react';
import { Notebook, Source, Note, Workflow, ViewMode } from '../types';
import { Book, FileText, Link as LinkIcon, Plus, File, GitMerge, MessageSquare, Edit2, Check, X } from 'lucide-react';

interface Props {
  notebooks: Notebook[];
  activeNotebookId: string | null;
  setActiveNotebookId: (id: string) => void;
  onCreateNotebook: (name: string, desc: string) => void;
  onUpdateNotebook: (id: string, name: string, desc: string) => void;
  sources: Source[];
  onAddSource: (title: string, content: string, type: 'text'|'url'|'file', url?: string) => void;
  notes: Note[];
  workflows: Workflow[];
  viewMode: ViewMode;
  setViewMode: (mode: ViewMode) => void;
  setActiveItemId: (id: string | null) => void;
  activeItemId: string | null;
}

export default function SidebarLeft({
  notebooks, activeNotebookId, setActiveNotebookId, onCreateNotebook, onUpdateNotebook,
  sources, onAddSource, notes, workflows, viewMode, setViewMode, setActiveItemId, activeItemId
}: Props) {
  const [isCreatingNotebook, setIsCreatingNotebook] = useState(false);
  const [newNbName, setNewNbName] = useState('');
  
  const [isAddingSource, setIsAddingSource] = useState(false);
  const [newSourceTitle, setNewSourceTitle] = useState('');
  const [newSourceContent, setNewSourceContent] = useState('');

  const [editingNotebookId, setEditingNotebookId] = useState<string | null>(null);
  const [editNbName, setEditNbName] = useState('');

  const activeNotebook = notebooks.find(nb => nb.id === activeNotebookId);

  useEffect(() => {
    if (editingNotebookId) {
      const nb = notebooks.find(n => n.id === editingNotebookId);
      if (nb) setEditNbName(nb.name);
    }
  }, [editingNotebookId, notebooks]);

  const handleSaveNotebookName = () => {
    if (editingNotebookId && activeNotebook) {
      onUpdateNotebook(editingNotebookId, editNbName, activeNotebook.description);
      setEditingNotebookId(null);
    }
  };

  return (
    <div className="w-64 border-r border-zinc-200 dark:border-zinc-800 bg-zinc-100 dark:bg-zinc-900 flex flex-col h-full shrink-0 transition-colors">
      <div className="p-4 border-b border-zinc-200 dark:border-zinc-800">
        {activeNotebook && (
          <div className="flex items-center justify-between group">
            {editingNotebookId === activeNotebook.id ? (
              <div className="flex items-center gap-1 w-full">
                <input 
                  type="text" 
                  value={editNbName} 
                  onChange={e => setEditNbName(e.target.value)}
                  className="flex-1 px-2 py-1 text-sm font-semibold border border-zinc-300 dark:border-zinc-700 rounded bg-white dark:bg-zinc-800 dark:text-zinc-200"
                  autoFocus
                  onKeyDown={e => {
                    if (e.key === 'Enter') handleSaveNotebookName();
                    if (e.key === 'Escape') setEditingNotebookId(null);
                  }}
                />
                <button onClick={handleSaveNotebookName} className="p-1 text-green-600 hover:bg-green-50 dark:hover:bg-green-900/20 rounded">
                  <Check size={14} />
                </button>
                <button onClick={() => setEditingNotebookId(null)} className="p-1 text-zinc-500 hover:bg-zinc-200 dark:hover:bg-zinc-800 rounded">
                  <X size={14} />
                </button>
              </div>
            ) : (
              <>
                <h1 className="text-sm font-bold text-zinc-800 dark:text-zinc-200 truncate pr-2">{activeNotebook.name}</h1>
                <button 
                  onClick={() => setEditingNotebookId(activeNotebook.id)}
                  className="p-1 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300 opacity-0 group-hover:opacity-100 transition-opacity rounded hover:bg-zinc-200 dark:hover:bg-zinc-800"
                >
                  <Edit2 size={12} />
                </button>
              </>
            )}
          </div>
        )}
      </div>
      <div className="flex-1 overflow-y-auto p-4 space-y-6">
        
        {/* Chat */}
        <div className="space-y-1">
          <button 
            onClick={() => { setViewMode('chat'); setActiveItemId(null); }}
            className={`flex items-center gap-2 w-full px-2 py-1.5 rounded text-sm transition-colors ${viewMode === 'chat' ? 'bg-zinc-200 dark:bg-zinc-800 font-medium dark:text-zinc-100' : 'hover:bg-zinc-200/50 dark:hover:bg-zinc-800/50 dark:text-zinc-300'}`}
          >
            <MessageSquare size={16} className="text-zinc-500 dark:text-zinc-400" />
            Agent Chat
          </button>
          
          <button 
            onClick={() => { setViewMode('data'); setActiveItemId(null); }}
            className={`flex items-center gap-2 w-full px-2 py-1.5 rounded text-sm transition-colors ${viewMode === 'data' ? 'bg-zinc-200 dark:bg-zinc-800 font-medium dark:text-zinc-100' : 'hover:bg-zinc-200/50 dark:hover:bg-zinc-800/50 dark:text-zinc-300'}`}
          >
            <Book size={16} className="text-zinc-500 dark:text-zinc-400" />
            Data Tools
          </button>
        </div>

        {/* Sources */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-xs font-semibold text-zinc-500 dark:text-zinc-400 uppercase tracking-wider">Sources</h2>
            <button onClick={() => setIsAddingSource(!isAddingSource)} className="p-1 hover:bg-zinc-200 dark:hover:bg-zinc-800 rounded dark:text-zinc-300">
              <Plus size={14} />
            </button>
          </div>
          
          {isAddingSource && (
            <div className="mb-3 p-2 bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded shadow-sm flex flex-col gap-2">
              <input 
                type="text" placeholder="Title" value={newSourceTitle} onChange={e => setNewSourceTitle(e.target.value)}
                className="px-2 py-1 text-sm border border-zinc-200 dark:border-zinc-700 rounded dark:bg-zinc-900 dark:text-zinc-200"
              />
              <textarea 
                placeholder="Paste content here..." value={newSourceContent} onChange={e => setNewSourceContent(e.target.value)}
                className="px-2 py-1 text-sm border border-zinc-200 dark:border-zinc-700 rounded h-20 resize-none dark:bg-zinc-900 dark:text-zinc-200"
              />
              <button 
                onClick={() => { onAddSource(newSourceTitle, newSourceContent, 'text'); setIsAddingSource(false); setNewSourceTitle(''); setNewSourceContent(''); }}
                className="px-2 py-1 bg-zinc-800 dark:bg-zinc-700 text-white text-xs rounded"
              >Add Source</button>
            </div>
          )}

          <div className="space-y-1">
            {sources.map(s => (
              <button 
                key={s.id}
                onClick={() => { setViewMode('source'); setActiveItemId(s.id); }}
                className={`flex items-center gap-2 w-full px-2 py-1.5 rounded text-sm text-left truncate transition-colors ${viewMode === 'source' && activeItemId === s.id ? 'bg-zinc-200 dark:bg-zinc-800 font-medium dark:text-zinc-100' : 'hover:bg-zinc-200/50 dark:hover:bg-zinc-800/50 dark:text-zinc-300'}`}
              >
                {s.type === 'url' ? <LinkIcon size={14} className="text-zinc-400 shrink-0" /> : <FileText size={14} className="text-zinc-400 shrink-0" />}
                <span className="truncate">{s.title}</span>
              </button>
            ))}
            {sources.length === 0 && <p className="text-xs text-zinc-400 dark:text-zinc-500 italic px-2">No sources yet</p>}
          </div>
        </div>

        {/* Notes */}
        <div>
          <h2 className="text-xs font-semibold text-zinc-500 dark:text-zinc-400 uppercase tracking-wider mb-2">Notes</h2>
          <div className="space-y-1">
            {notes.map(n => (
              <button 
                key={n.id}
                onClick={() => { setViewMode('note'); setActiveItemId(n.id); }}
                className={`flex items-center gap-2 w-full px-2 py-1.5 rounded text-sm text-left truncate transition-colors ${viewMode === 'note' && activeItemId === n.id ? 'bg-zinc-200 dark:bg-zinc-800 font-medium dark:text-zinc-100' : 'hover:bg-zinc-200/50 dark:hover:bg-zinc-800/50 dark:text-zinc-300'}`}
              >
                <File size={14} className="text-zinc-400 shrink-0" />
                <span className="truncate">{n.title || 'Untitled'}</span>
              </button>
            ))}
            {notes.length === 0 && <p className="text-xs text-zinc-400 dark:text-zinc-500 italic px-2">No notes yet</p>}
          </div>
        </div>

        {/* Workflows */}
        <div>
          <h2 className="text-xs font-semibold text-zinc-500 dark:text-zinc-400 uppercase tracking-wider mb-2">Workflows</h2>
          <div className="space-y-1">
            {workflows.map(w => (
              <button 
                key={w.id}
                onClick={() => { setViewMode('workflow'); setActiveItemId(w.id); }}
                className={`flex items-center gap-2 w-full px-2 py-1.5 rounded text-sm text-left truncate transition-colors ${viewMode === 'workflow' && activeItemId === w.id ? 'bg-zinc-200 dark:bg-zinc-800 font-medium dark:text-zinc-100' : 'hover:bg-zinc-200/50 dark:hover:bg-zinc-800/50 dark:text-zinc-300'}`}
              >
                <GitMerge size={14} className="text-zinc-400 shrink-0" />
                <span className="truncate">{w.name}</span>
              </button>
            ))}
            {workflows.length === 0 && <p className="text-xs text-zinc-400 dark:text-zinc-500 italic px-2">No workflows yet</p>}
          </div>
        </div>

      </div>
    </div>
  );
}
