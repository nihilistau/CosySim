import React, { useState, useEffect } from 'react';
import { Source } from '../types';
import { FileText, Link as LinkIcon, Edit2, Trash2, Save, X } from 'lucide-react';

interface Props {
  sourceId: string;
  sources: Source[];
  onUpdateSource: (id: string, title: string, content: string) => void;
  onDeleteSource: (id: string) => void;
}

export default function SourceViewer({ sourceId, sources, onUpdateSource, onDeleteSource }: Props) {
  const source = sources.find(s => s.id === sourceId);
  const [isEditing, setIsEditing] = useState(false);
  const [editTitle, setEditTitle] = useState('');
  const [editContent, setEditContent] = useState('');

  useEffect(() => {
    if (source) {
      setEditTitle(source.title);
      setEditContent(source.content);
      setIsEditing(false);
    }
  }, [sourceId, source]);

  if (!source) return <div className="p-8 text-zinc-500">Source not found.</div>;

  const handleSave = () => {
    onUpdateSource(source.id, editTitle, editContent);
    setIsEditing(false);
  };

  return (
    <div className="flex flex-col h-full bg-white dark:bg-zinc-900 relative transition-colors">
      <div className="h-14 border-b border-zinc-200 dark:border-zinc-800 flex items-center justify-between px-6 shrink-0 bg-zinc-50/50 dark:bg-zinc-900/50 transition-colors">
        <div className="flex items-center gap-3 flex-1 mr-4">
          {source.type === 'url' ? <LinkIcon size={18} className="text-zinc-400 dark:text-zinc-500" /> : <FileText size={18} className="text-zinc-400 dark:text-zinc-500" />}
          {isEditing ? (
            <input 
              value={editTitle}
              onChange={e => setEditTitle(e.target.value)}
              className="flex-1 bg-white dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 rounded px-2 py-1 text-sm dark:text-zinc-200"
            />
          ) : (
            <h1 className="text-lg font-semibold text-zinc-800 dark:text-zinc-200 truncate max-w-md">{source.title}</h1>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-zinc-500 dark:text-zinc-400 uppercase tracking-wider bg-zinc-200 dark:bg-zinc-800 px-2 py-1 rounded mr-2">{source.type}</span>
          {isEditing ? (
            <>
              <button onClick={handleSave} className="p-1.5 text-green-600 hover:bg-green-50 dark:hover:bg-green-900/20 rounded transition-colors" title="Save">
                <Save size={16} />
              </button>
              <button onClick={() => setIsEditing(false)} className="p-1.5 text-zinc-500 hover:bg-zinc-200 dark:hover:bg-zinc-800 rounded transition-colors" title="Cancel">
                <X size={16} />
              </button>
            </>
          ) : (
            <>
              <button onClick={() => setIsEditing(true)} className="p-1.5 text-zinc-500 hover:bg-zinc-200 dark:hover:bg-zinc-800 rounded transition-colors" title="Edit">
                <Edit2 size={16} />
              </button>
              <button onClick={() => onDeleteSource(source.id)} className="p-1.5 text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 rounded transition-colors" title="Delete">
                <Trash2 size={16} />
              </button>
            </>
          )}
        </div>
      </div>
      
      <div className="flex-1 overflow-y-auto p-8 bg-zinc-50 dark:bg-zinc-950 transition-colors">
        <div className="max-w-3xl mx-auto bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 shadow-sm rounded-xl p-8 transition-colors h-full flex flex-col">
          {source.url && !isEditing && (
            <a href={source.url} target="_blank" rel="noreferrer" className="text-sm text-blue-600 dark:text-blue-400 hover:underline mb-6 block">
              {source.url}
            </a>
          )}
          <div className="max-w-none flex-1 flex flex-col">
            {isEditing ? (
              <textarea 
                value={editContent}
                onChange={e => setEditContent(e.target.value)}
                className="w-full flex-1 bg-white dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 rounded p-4 text-sm font-sans dark:text-zinc-200 resize-none min-h-[400px]"
              />
            ) : (
              <pre className="whitespace-pre-wrap font-sans text-sm text-zinc-700 dark:text-zinc-300 leading-relaxed bg-transparent p-0 m-0 border-none">
                {source.content}
              </pre>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
