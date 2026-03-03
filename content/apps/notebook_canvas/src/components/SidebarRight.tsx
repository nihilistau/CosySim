import React, { useState } from 'react';
import { ViewMode } from '../types';
import { Settings, FilePlus, GitBranchPlus, Moon, Sun, Brain, BookOpen, Sparkles, Users, BarChart2, Cpu, FileText, Zap, Github } from 'lucide-react';

const PANEL_BUTTONS: { mode: ViewMode; label: string; icon: React.ReactNode; color: string }[] = [
  { mode: 'nexus',    label: 'Nexus',     icon: <Brain size={14} />,      color: 'text-violet-500 dark:text-violet-400' },
  { mode: 'nlm',      label: 'NLM',       icon: <BookOpen size={14} />,   color: 'text-purple-500 dark:text-purple-400' },
  { mode: 'aistudio', label: 'AI Studio', icon: <Sparkles size={14} />,   color: 'text-blue-500 dark:text-blue-400' },
  { mode: 'copilot',  label: 'Copilot',   icon: <Github size={14} />,     color: 'text-white dark:text-zinc-200' },
  { mode: 'accounts', label: 'Accounts',  icon: <Users size={14} />,      color: 'text-emerald-500 dark:text-emerald-400' },
  { mode: 'training', label: 'Training',  icon: <BarChart2 size={14} />,  color: 'text-amber-500 dark:text-amber-400' },
  { mode: 'compute',  label: 'Compute',   icon: <Cpu size={14} />,        color: 'text-orange-500 dark:text-orange-400' },
  { mode: 'har',      label: 'HAR Explorer', icon: <FileText size={14} />, color: 'text-cyan-500 dark:text-cyan-400' },
  { mode: 'rpc',      label: 'RPC Explorer', icon: <Zap size={14} />,     color: 'text-yellow-500 dark:text-yellow-400' },
];

interface Props {
  lmStudioUrl: string;
  setLmStudioUrl: (url: string) => void;
  onCreateNote: (title: string) => void;
  onCreateWorkflow: (name: string) => void;
  viewMode: ViewMode;
  setViewMode: (mode: ViewMode) => void;
  isDarkMode: boolean;
  setIsDarkMode: (val: boolean) => void;
}

export default function SidebarRight({ lmStudioUrl, setLmStudioUrl, onCreateNote, onCreateWorkflow, viewMode, setViewMode, isDarkMode, setIsDarkMode }: Props) {
  const [isCreatingNote, setIsCreatingNote] = useState(false);
  const [newNoteTitle, setNewNoteTitle] = useState('');
  
  const [isCreatingWorkflow, setIsCreatingWorkflow] = useState(false);
  const [newWorkflowName, setNewWorkflowName] = useState('');

  return (
    <div className="w-64 border-l border-zinc-200 dark:border-zinc-800 bg-zinc-100 dark:bg-zinc-900 flex flex-col h-full shrink-0 transition-colors">
      <div className="p-3 border-b border-zinc-200 dark:border-zinc-800">
        <h2 className="text-xs font-semibold text-zinc-500 dark:text-zinc-400 uppercase tracking-wider mb-2">System Panels</h2>
        <div className="grid grid-cols-1 gap-1">
          {PANEL_BUTTONS.map(({ mode, label, icon, color }) => (
            <button
              key={mode}
              onClick={() => setViewMode(mode)}
              className={`flex items-center gap-2 px-3 py-2 rounded text-xs font-medium transition-colors w-full text-left ${
                viewMode === mode
                  ? 'bg-zinc-200 dark:bg-zinc-700 text-zinc-900 dark:text-zinc-100'
                  : 'hover:bg-zinc-200 dark:hover:bg-zinc-800 text-zinc-600 dark:text-zinc-400'
              }`}
            >
              <span className={color}>{icon}</span>
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="p-4 border-b border-zinc-200 dark:border-zinc-800">
        <div className="flex justify-between items-center mb-4">
          <h2 className="text-xs font-semibold text-zinc-500 dark:text-zinc-400 uppercase tracking-wider flex items-center gap-2">
            <Settings size={14} /> Settings
          </h2>
          <button 
            onClick={() => setIsDarkMode(!isDarkMode)}
            className="p-1.5 rounded-md hover:bg-zinc-200 dark:hover:bg-zinc-800 text-zinc-500 dark:text-zinc-400 transition-colors"
          >
            {isDarkMode ? <Sun size={14} /> : <Moon size={14} />}
          </button>
        </div>
        <div className="space-y-2">
          <label className="text-xs text-zinc-600 dark:text-zinc-400 block">LMStudio API URL</label>
          <input 
            type="text" 
            value={lmStudioUrl} 
            onChange={e => setLmStudioUrl(e.target.value)} 
            className="w-full px-2 py-1.5 text-xs border border-zinc-300 dark:border-zinc-700 rounded bg-white dark:bg-zinc-800 dark:text-zinc-200"
            placeholder="http://localhost:1234/v1"
          />
          <p className="text-[10px] text-zinc-400 dark:text-zinc-500 mt-1 leading-tight">
            Ensure LMStudio is running locally with CORS enabled.
          </p>
        </div>
      </div>

      <div className="p-4 flex-1 overflow-y-auto">
        <h2 className="text-xs font-semibold text-zinc-500 dark:text-zinc-400 uppercase tracking-wider mb-4">Operations</h2>
        
        <div className="space-y-4">
          {/* Create Note */}
          <div className="bg-white dark:bg-zinc-800 p-3 rounded border border-zinc-200 dark:border-zinc-700 shadow-sm transition-colors">
            <button 
              onClick={() => setIsCreatingNote(!isCreatingNote)}
              className="flex items-center gap-2 text-sm font-medium w-full text-left dark:text-zinc-200"
            >
              <FilePlus size={16} className="text-zinc-500 dark:text-zinc-400" />
              New Note
            </button>
            {isCreatingNote && (
              <div className="mt-3 flex flex-col gap-2">
                <input 
                  type="text" placeholder="Note Title" value={newNoteTitle} onChange={e => setNewNoteTitle(e.target.value)}
                  className="px-2 py-1 text-xs border border-zinc-200 dark:border-zinc-700 rounded dark:bg-zinc-900 dark:text-zinc-200"
                />
                <button 
                  onClick={() => { onCreateNote(newNoteTitle); setIsCreatingNote(false); setNewNoteTitle(''); }}
                  className="px-2 py-1 bg-zinc-800 dark:bg-zinc-700 text-white text-xs rounded"
                >Create</button>
              </div>
            )}
          </div>

          {/* Create Workflow */}
          <div className="bg-white dark:bg-zinc-800 p-3 rounded border border-zinc-200 dark:border-zinc-700 shadow-sm transition-colors">
            <button 
              onClick={() => setIsCreatingWorkflow(!isCreatingWorkflow)}
              className="flex items-center gap-2 text-sm font-medium w-full text-left dark:text-zinc-200"
            >
              <GitBranchPlus size={16} className="text-zinc-500 dark:text-zinc-400" />
              New Workflow
            </button>
            {isCreatingWorkflow && (
              <div className="mt-3 flex flex-col gap-2">
                <input 
                  type="text" placeholder="Workflow Name" value={newWorkflowName} onChange={e => setNewWorkflowName(e.target.value)}
                  className="px-2 py-1 text-xs border border-zinc-200 dark:border-zinc-700 rounded dark:bg-zinc-900 dark:text-zinc-200"
                />
                <button 
                  onClick={() => { onCreateWorkflow(newWorkflowName); setIsCreatingWorkflow(false); setNewWorkflowName(''); }}
                  className="px-2 py-1 bg-zinc-800 dark:bg-zinc-700 text-white text-xs rounded"
                >Create</button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
