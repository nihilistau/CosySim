import React, { useState, useEffect } from 'react';
import { Note } from '../types';
import { Save } from 'lucide-react';

interface Props {
  noteId: string;
  notes: Note[];
  setNotes: React.Dispatch<React.SetStateAction<Note[]>>;
}

export default function NoteEditor({ noteId, notes, setNotes }: Props) {
  const note = notes.find(n => n.id === noteId);
  const [title, setTitle] = useState(note?.title || '');
  const [content, setContent] = useState(note?.content || '');
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    if (note) {
      setTitle(note.title);
      setContent(note.content);
    }
  }, [noteId, note]);

  const handleSave = async () => {
    if (!note) return;
    setIsSaving(true);
    await fetch(`/api/notes/${note.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, content })
    });
    setNotes(prev => prev.map(n => n.id === note.id ? { ...n, title, content } : n));
    setIsSaving(false);
  };

  if (!note) return <div className="p-8 text-zinc-500">Note not found.</div>;

  return (
    <div className="flex flex-col h-full bg-white dark:bg-zinc-900 relative transition-colors">
      <div className="h-14 border-b border-zinc-200 dark:border-zinc-800 flex items-center justify-between px-6 shrink-0 bg-zinc-50/50 dark:bg-zinc-900/50 transition-colors">
        <input 
          type="text" 
          value={title} 
          onChange={e => setTitle(e.target.value)} 
          className="text-lg font-semibold text-zinc-800 dark:text-zinc-200 bg-transparent border-none focus:outline-none focus:ring-0 w-1/2"
          placeholder="Note Title"
        />
        <button 
          onClick={handleSave}
          disabled={isSaving}
          className="flex items-center gap-2 text-xs font-medium text-white bg-zinc-800 dark:bg-zinc-700 hover:bg-zinc-700 dark:hover:bg-zinc-600 px-3 py-1.5 rounded transition-colors disabled:opacity-50"
        >
          <Save size={14} />
          {isSaving ? 'Saving...' : 'Save Note'}
        </button>
      </div>
      
      <div className="flex-1 overflow-y-auto p-6 bg-white dark:bg-zinc-900 transition-colors">
        <textarea 
          value={content} 
          onChange={e => setContent(e.target.value)} 
          className="w-full h-full resize-none bg-transparent border-none focus:outline-none focus:ring-0 text-zinc-700 dark:text-zinc-300 leading-relaxed font-serif text-lg"
          placeholder="Start writing your note here..."
        />
      </div>
    </div>
  );
}
