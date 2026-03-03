/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState, useEffect, useRef } from 'react';
import { Notebook, Source, Note, Workflow, ViewMode } from './types';
import SidebarLeft from './components/SidebarLeft';
import Canvas from './components/Canvas';
import SidebarRight from './components/SidebarRight';
import DataTools from './components/DataTools';
import { v4 as uuidv4 } from 'uuid';
import { Download, Upload, Plus } from 'lucide-react';

export default function App() {
  const [notebooks, setNotebooks] = useState<Notebook[]>([]);
  const [activeNotebookId, setActiveNotebookId] = useState<string | null>(null);
  
  const [sources, setSources] = useState<Source[]>([]);
  const [notes, setNotes] = useState<Note[]>([]);
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  
  const [viewMode, setViewMode] = useState<ViewMode>('chat');
  const [activeItemId, setActiveItemId] = useState<string | null>(null); // ID of active note, workflow, or source
  
  const [lmStudioUrl, setLmStudioUrl] = useState('http://localhost:1234/v1');
  const [isDarkMode, setIsDarkMode] = useState(false);

  // Apply dark mode to document
  useEffect(() => {
    if (isDarkMode) {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, [isDarkMode]);

  // Fetch notebooks on load
  useEffect(() => {
    fetch('/api/notebooks')
      .then(res => res.json())
      .then(data => {
        setNotebooks(data);
        if (data.length > 0 && !activeNotebookId) {
          setActiveNotebookId(data[0].id);
        }
      })
      .catch(err => console.error("Failed to fetch notebooks", err));
  }, []);

  // Fetch notebook contents when active notebook changes
  useEffect(() => {
    if (!activeNotebookId) return;
    
    fetch(`/api/notebooks/${activeNotebookId}/sources`)
      .then(res => res.json())
      .then(setSources);
      
    fetch(`/api/notebooks/${activeNotebookId}/notes`)
      .then(res => res.json())
      .then(setNotes);
      
    fetch(`/api/notebooks/${activeNotebookId}/workflows`)
      .then(res => res.json())
      .then(setWorkflows);
      
  }, [activeNotebookId]);

  const handleCreateNotebook = async (name: string, description: string) => {
    const newNotebook = { id: uuidv4(), name, description };
    await fetch('/api/notebooks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(newNotebook)
    });
    setNotebooks([newNotebook, ...notebooks]);
    setActiveNotebookId(newNotebook.id);
    setActiveItemId(null);
    setViewMode('chat');
  };

  const handleUpdateNotebook = async (id: string, name: string, description: string) => {
    await fetch(`/api/notebooks/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, description })
    });
    setNotebooks(prev => prev.map(nb => nb.id === id ? { ...nb, name, description } : nb));
  };

  const handleAddSource = async (title: string, content: string, type: 'text'|'url'|'file', url?: string) => {
    if (!activeNotebookId) return;
    const newSource = { id: uuidv4(), notebook_id: activeNotebookId, title, content, type, url };
    await fetch(`/api/notebooks/${activeNotebookId}/sources`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(newSource)
    });
    setSources([newSource, ...sources]);
  };

  const handleUpdateSource = async (sourceId: string, title: string, content: string) => {
    await fetch(`/api/sources/${sourceId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, content })
    });
    setSources(prev => prev.map(s => s.id === sourceId ? { ...s, title, content } : s));
  };

  const handleDeleteSource = async (sourceId: string) => {
    await fetch(`/api/sources/${sourceId}`, { method: 'DELETE' });
    setSources(prev => prev.filter(s => s.id !== sourceId));
    if (activeItemId === sourceId) {
      setViewMode('chat');
      setActiveItemId(null);
    }
  };

  const handleCreateNote = async (title: string) => {
    if (!activeNotebookId) return;
    const newNote = { id: uuidv4(), notebook_id: activeNotebookId, title, content: '' };
    await fetch(`/api/notebooks/${activeNotebookId}/notes`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(newNote)
    });
    setNotes([newNote, ...notes]);
    setViewMode('note');
    setActiveItemId(newNote.id);
  };

  const handleCreateWorkflow = async (name: string) => {
    if (!activeNotebookId) return;
    const newWorkflow = { id: uuidv4(), notebook_id: activeNotebookId, name, nodes: '[]', edges: '[]' };
    await fetch(`/api/notebooks/${activeNotebookId}/workflows`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(newWorkflow)
    });
    setWorkflows([newWorkflow, ...workflows]);
    setViewMode('workflow');
    setActiveItemId(newWorkflow.id);
  };

  const handleExport = () => {
    const data = { notebooks, sources, notes, workflows };
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `nexus-export-${new Date().toISOString().split('T')[0]}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const fileInputRef = useRef<HTMLInputElement>(null);
  const handleImport = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = async (event) => {
      try {
        const data = JSON.parse(event.target?.result as string);
        // In a real app we'd send these to the backend. For now, we'll just set state if it matches the current notebook,
        // or ideally we'd have a bulk import API. Since we are using a mock/local backend, we might need to just reload.
        // For simplicity, we'll just alert that import is a placeholder unless we implement bulk import.
        alert('Import functionality requires backend support for bulk insert. State loaded locally for preview.');
        if (data.notebooks) setNotebooks(data.notebooks);
        if (data.sources) setSources(data.sources);
        if (data.notes) setNotes(data.notes);
        if (data.workflows) setWorkflows(data.workflows);
      } catch (err) {
        console.error('Failed to parse import file', err);
      }
    };
    reader.readAsText(file);
  };

  return (
    <div className="flex flex-col h-screen w-full bg-zinc-50 dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100 overflow-hidden font-sans transition-colors">
      {/* Top Bar: Notebook Tabs & Export/Import */}
      <div className="flex items-center justify-between px-2 bg-zinc-200 dark:bg-zinc-900 border-b border-zinc-300 dark:border-zinc-800 shrink-0 h-10 transition-colors overflow-x-auto">
        <div className="flex items-center gap-1 h-full">
          {notebooks.map(nb => (
            <button
              key={nb.id}
              onClick={() => setActiveNotebookId(nb.id)}
              className={`px-4 h-full text-sm font-medium border-r border-zinc-300 dark:border-zinc-800 transition-colors flex items-center ${
                activeNotebookId === nb.id 
                  ? 'bg-white dark:bg-zinc-950 text-blue-600 dark:text-blue-400 border-t-2 border-t-blue-500' 
                  : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-50 dark:hover:bg-zinc-700 border-t-2 border-t-transparent'
              }`}
            >
              {nb.name}
            </button>
          ))}
          <button 
            onClick={() => handleCreateNotebook('New Notebook', '')}
            className="p-1.5 ml-1 text-zinc-500 hover:bg-zinc-300 dark:hover:bg-zinc-700 rounded transition-colors"
            title="New Notebook"
          >
            <Plus size={16} />
          </button>
        </div>
        <div className="flex items-center gap-2 px-2 shrink-0">
          <input type="file" accept=".json" ref={fileInputRef} onChange={handleImport} className="hidden" />
          <button onClick={() => fileInputRef.current?.click()} className="flex items-center gap-1 px-2 py-1 text-xs bg-zinc-100 dark:bg-zinc-800 hover:bg-zinc-200 dark:hover:bg-zinc-700 rounded border border-zinc-300 dark:border-zinc-700 transition-colors">
            <Upload size={14} /> Import
          </button>
          <button onClick={handleExport} className="flex items-center gap-1 px-2 py-1 text-xs bg-zinc-100 dark:bg-zinc-800 hover:bg-zinc-200 dark:hover:bg-zinc-700 rounded border border-zinc-300 dark:border-zinc-700 transition-colors">
            <Download size={14} /> Export
          </button>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* Left Sidebar: Sources & Notebooks */}
        <SidebarLeft 
          notebooks={notebooks}
          activeNotebookId={activeNotebookId}
          setActiveNotebookId={setActiveNotebookId}
          onCreateNotebook={handleCreateNotebook}
          onUpdateNotebook={handleUpdateNotebook}
          sources={sources}
          onAddSource={handleAddSource}
          notes={notes}
          workflows={workflows}
          viewMode={viewMode}
          setViewMode={setViewMode}
          setActiveItemId={setActiveItemId}
          activeItemId={activeItemId}
        />
        
        {/* Middle Canvas: Chat, Editor, Workflow */}
        <Canvas 
          viewMode={viewMode}
          activeItemId={activeItemId}
          activeNotebookId={activeNotebookId}
          sources={sources}
          notes={notes}
          workflows={workflows}
          lmStudioUrl={lmStudioUrl}
          setNotes={setNotes}
          setWorkflows={setWorkflows}
          onAddSource={handleAddSource}
          onUpdateSource={handleUpdateSource}
          onDeleteSource={handleDeleteSource}
          isDarkMode={isDarkMode}
          setActiveItemId={setActiveItemId}
          setViewMode={setViewMode}
        />
        
        {/* Right Sidebar: Operations & Tools */}
        <SidebarRight 
          lmStudioUrl={lmStudioUrl}
          setLmStudioUrl={setLmStudioUrl}
          onCreateNote={handleCreateNote}
          onCreateWorkflow={handleCreateWorkflow}
          viewMode={viewMode}
          setViewMode={setViewMode}
          isDarkMode={isDarkMode}
          setIsDarkMode={setIsDarkMode}
        />
      </div>
    </div>
  );
}
