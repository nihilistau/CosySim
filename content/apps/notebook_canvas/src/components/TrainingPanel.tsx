import React, { useState, useEffect } from 'react';
import { RefreshCw, ThumbsUp, ThumbsDown, Loader, BarChart2, ChevronLeft, ChevronRight, Code } from 'lucide-react';

interface TrainingStats {
  total_examples: number;
  by_type: {
    conversations: number;
    tool_calls: number;
    code: number;
    grammar_errors: number;
    vscode_history?: number;
  };
}

interface TrainingExample {
  instruction?: string;
  input?: string;
  output?: string;
  messages?: Array<{ role: string; content: string }>;
  rating?: number;
  source?: string;
  language?: string;
}

interface Props {}

// TODO: GET /api/training/examples endpoint needed
const PLACEHOLDER_EXAMPLES: TrainingExample[] = [
  { instruction: 'Add type hints to this function', input: 'def add(a, b):\n    return a + b', output: 'def add(a: int, b: int) -> int:\n    return a + b', source: 'code', language: 'python' },
  { instruction: 'Write a docstring for this class', input: 'class UserManager:\n    def __init__(self):\n        self.users = {}', output: 'class UserManager:\n    """Manages user records in memory."""\n    def __init__(self):\n        self.users = {}', source: 'code', language: 'python' },
  { instruction: 'Fix the grammar in this sentence', input: 'The function dont works when input is null.', output: 'The function doesn\'t work when the input is null.', source: 'grammar_errors', language: 'en' },
  { instruction: 'Refactor this loop to use list comprehension', input: 'result = []\nfor x in items:\n    if x > 0:\n        result.append(x * 2)', output: 'result = [x * 2 for x in items if x > 0]', source: 'code', language: 'python' },
  { messages: [{ role: 'user', content: 'How do I reverse a string in Python?' }, { role: 'assistant', content: 'Use slicing: `s[::-1]`. For example, `"hello"[::-1]` returns `"olleh"`.' }], source: 'conversations' },
  { instruction: 'Convert this for loop to functional style', input: 'total = 0\nfor n in numbers:\n    total += n', output: 'total = sum(numbers)', source: 'code', language: 'python' },
  { instruction: 'Add error handling', input: 'def read_file(path):\n    with open(path) as f:\n        return f.read()', output: 'def read_file(path: str) -> str:\n    try:\n        with open(path) as f:\n            return f.read()\n    except FileNotFoundError:\n        raise FileNotFoundError(f"File not found: {path}")', source: 'code', language: 'python' },
  { messages: [{ role: 'user', content: 'What is the difference between `is` and `==` in Python?' }, { role: 'assistant', content: '`==` checks value equality. `is` checks identity (same object in memory). For example, `[1] == [1]` is True but `[1] is [1]` is False.' }], source: 'conversations' },
  { instruction: 'Fix the grammar error', input: 'He dont know nothing about the subject.', output: 'He doesn\'t know anything about the subject.', source: 'grammar_errors', language: 'en' },
  { instruction: 'Add type annotations and docstring', input: 'def process(data, config):\n    return {k: v for k, v in data.items() if k in config}', output: 'from typing import Dict, Any\n\ndef process(data: Dict[str, Any], config: list) -> Dict[str, Any]:\n    """Filter data dictionary to only include keys present in config.\n\n    Args:\n        data: Source dictionary.\n        config: List of allowed keys.\n\n    Returns:\n        Filtered dictionary.\n    """\n    return {k: v for k, v in data.items() if k in config}', source: 'code', language: 'python' },
  { messages: [{ role: 'user', content: 'How do I create a virtual environment?' }, { role: 'assistant', content: 'Run `python -m venv venv` to create one. Activate with `source venv/bin/activate` (Unix) or `venv\\Scripts\\activate` (Windows).' }], source: 'conversations' },
  { instruction: 'Simplify this conditional', input: 'if condition == True:\n    return True\nelse:\n    return False', output: 'return condition', source: 'code', language: 'python' },
  { instruction: 'Correct the grammar', input: 'The datas was processed successfully by the algorithm.', output: 'The data was processed successfully by the algorithm.', source: 'grammar_errors', language: 'en' },
  { messages: [{ role: 'user', content: 'What does `*args` mean in Python?' }, { role: 'assistant', content: '`*args` allows a function to accept any number of positional arguments, collected into a tuple. Example: `def f(*args): print(args)`.' }], source: 'conversations' },
  { instruction: 'Add logging to this function', input: 'def save_user(user):\n    db.insert(user)\n    return True', output: 'import logging\nlogger = logging.getLogger(__name__)\n\ndef save_user(user: dict) -> bool:\n    logger.info("Saving user: %s", user.get("id"))\n    db.insert(user)\n    logger.debug("User saved successfully")\n    return True', source: 'code', language: 'python' },
  { messages: [{ role: 'user', content: 'Explain list slicing in Python.' }, { role: 'assistant', content: 'Slice syntax is `list[start:stop:step]`. `start` is inclusive, `stop` is exclusive. Omit any part to use defaults: start=0, stop=end, step=1.' }], source: 'conversations' },
  { instruction: 'Convert this class to use dataclasses', input: 'class Point:\n    def __init__(self, x, y):\n        self.x = x\n        self.y = y', output: 'from dataclasses import dataclass\n\n@dataclass\nclass Point:\n    x: float\n    y: float', source: 'code', language: 'python' },
  { instruction: 'Fix grammar issues', input: 'There are less errors in the new version of the softwares.', output: 'There are fewer errors in the new version of the software.', source: 'grammar_errors', language: 'en' },
  { messages: [{ role: 'user', content: 'How do I iterate over a dictionary?' }, { role: 'assistant', content: 'Use `.items()` for key-value pairs: `for k, v in d.items()`. Use `.keys()` for just keys, `.values()` for just values.' }], source: 'conversations' },
  { instruction: 'Add input validation', input: 'def divide(a, b):\n    return a / b', output: 'def divide(a: float, b: float) -> float:\n    if b == 0:\n        raise ValueError("Divisor cannot be zero")\n    return a / b', source: 'code', language: 'python' },
];

function StatCard({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="p-3 bg-zinc-50 dark:bg-zinc-800/60 border border-zinc-200 dark:border-zinc-700 rounded-xl">
      <p className={`text-lg font-bold ${color}`}>{value.toLocaleString()}</p>
      <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">{label}</p>
    </div>
  );
}

function CodeBlock({ code, tint }: { code: string; tint?: 'emerald' }) {
  return (
    <pre className={`text-xs rounded-lg px-3 py-2.5 font-mono overflow-x-auto whitespace-pre-wrap leading-relaxed ${tint === 'emerald' ? 'bg-emerald-50 dark:bg-emerald-950/30 border border-emerald-200 dark:border-emerald-800 text-emerald-900 dark:text-emerald-100' : 'bg-zinc-100 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 text-zinc-800 dark:text-zinc-100'}`}>
      {code}
    </pre>
  );
}

export default function TrainingPanel({}: Props) {
  const [stats, setStats] = useState<TrainingStats | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [statsError, setStatsError] = useState<string | null>(null);
  const [reviewIdx, setReviewIdx] = useState(0);
  const [approvedCount, setApprovedCount] = useState(0);
  const [rejectedCount, setRejectedCount] = useState(0);
  const [actionMsg, setActionMsg] = useState<string | null>(null);
  const [isActioning, setIsActioning] = useState(false);

  const examples = PLACEHOLDER_EXAMPLES;

  const loadStats = async () => {
    setIsLoading(true);
    setStatsError(null);
    try {
      const res = await fetch('/api/training/stats');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setStats(data);
    } catch (e: any) {
      setStatsError(e.message);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => { loadStats(); }, []);

  const currentExample = examples[reviewIdx];

  const handleApprove = async () => {
    setIsActioning(true);
    try {
      const msgs = currentExample.messages ?? [
        ...(currentExample.instruction ? [{ role: 'user', content: `${currentExample.instruction}${currentExample.input ? `\n\n${currentExample.input}` : ''}` }] : []),
        ...(currentExample.output ? [{ role: 'assistant', content: currentExample.output }] : []),
      ];
      await fetch('/api/training/capture', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: msgs, rating: 1 }),
      });
      setApprovedCount(c => c + 1);
      setActionMsg('✓ Approved');
      setTimeout(() => { setActionMsg(null); if (reviewIdx < examples.length - 1) setReviewIdx(i => i + 1); }, 600);
    } catch (e: any) {
      setActionMsg(`Error: ${e.message}`);
    } finally {
      setIsActioning(false);
    }
  };

  const handleReject = () => {
    setRejectedCount(c => c + 1);
    setActionMsg('✗ Rejected');
    setTimeout(() => { setActionMsg(null); if (reviewIdx < examples.length - 1) setReviewIdx(i => i + 1); }, 600);
  };

  return (
    <div className="flex flex-col h-full bg-white dark:bg-zinc-900 overflow-y-auto transition-colors">
      {/* Header */}
      <div className="h-14 border-b border-zinc-200 dark:border-zinc-800 flex items-center justify-between px-6 shrink-0 bg-zinc-50/50 dark:bg-zinc-900/50">
        <div className="flex items-center gap-2">
          <BarChart2 size={16} className="text-violet-500" />
          <h1 className="text-sm font-bold tracking-widest text-zinc-700 dark:text-zinc-300 uppercase">Training Data</h1>
        </div>
        <button
          onClick={loadStats}
          disabled={isLoading}
          className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg bg-zinc-100 dark:bg-zinc-800 hover:bg-zinc-200 dark:hover:bg-zinc-700 text-zinc-600 dark:text-zinc-300 disabled:opacity-50 transition-colors"
        >
          <RefreshCw size={12} className={isLoading ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      <div className="p-6 space-y-6">
        {/* Stats grid */}
        {statsError && <p className="text-sm text-red-400">{statsError}</p>}
        {isLoading && !stats && (
          <div className="flex items-center justify-center h-20">
            <Loader size={18} className="animate-spin text-zinc-400" />
          </div>
        )}
        {stats && (
          <div>
            <h2 className="text-xs font-semibold text-zinc-500 dark:text-zinc-400 uppercase tracking-widest mb-3">Statistics</h2>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              <StatCard label="Total Examples" value={stats.total_examples} color="text-violet-600 dark:text-violet-400" />
              <StatCard label="Conversations" value={stats.by_type.conversations} color="text-blue-600 dark:text-blue-400" />
              <StatCard label="Tool Calls" value={stats.by_type.tool_calls} color="text-emerald-600 dark:text-emerald-400" />
              <StatCard label="Code" value={stats.by_type.code} color="text-amber-600 dark:text-amber-400" />
              <StatCard label="Grammar" value={stats.by_type.grammar_errors} color="text-rose-600 dark:text-rose-400" />
              {stats.by_type.vscode_history != null && (
                <StatCard label="VSCode History" value={stats.by_type.vscode_history} color="text-indigo-600 dark:text-indigo-400" />
              )}
            </div>
          </div>
        )}

        {/* Review queue */}
        <div className="border-t border-zinc-200 dark:border-zinc-700 pt-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xs font-semibold text-zinc-500 dark:text-zinc-400 uppercase tracking-widest">Review Queue</h2>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setReviewIdx(i => Math.max(0, i - 1))}
                disabled={reviewIdx === 0}
                className="p-1.5 rounded-lg hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-400 disabled:opacity-30 transition-colors"
              >
                <ChevronLeft size={15} />
              </button>
              <span className="text-xs text-zinc-500 dark:text-zinc-400 min-w-[60px] text-center">
                {reviewIdx + 1} of {examples.length}
              </span>
              <button
                onClick={() => setReviewIdx(i => Math.min(examples.length - 1, i + 1))}
                disabled={reviewIdx === examples.length - 1}
                className="p-1.5 rounded-lg hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-400 disabled:opacity-30 transition-colors"
              >
                <ChevronRight size={15} />
              </button>
            </div>
          </div>

          {/* Example metadata */}
          <div className="flex gap-2 mb-3 flex-wrap">
            {currentExample.source && (
              <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-violet-100 dark:bg-violet-900/40 text-violet-700 dark:text-violet-300">{currentExample.source}</span>
            )}
            {currentExample.language && (
              <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 flex items-center gap-1">
                <Code size={9} />
                {currentExample.language}
              </span>
            )}
          </div>

          {/* Example content */}
          <div className="bg-zinc-50 dark:bg-zinc-800/40 border border-zinc-200 dark:border-zinc-700 rounded-xl p-4 space-y-3">
            {currentExample.messages ? (
              <div className="space-y-3">
                {currentExample.messages.map((msg, i) => (
                  <div key={i}>
                    <p className={`text-[10px] font-semibold uppercase tracking-wide mb-1 ${msg.role === 'user' ? 'text-zinc-400' : 'text-emerald-600 dark:text-emerald-400'}`}>{msg.role}</p>
                    <p className="text-sm text-zinc-700 dark:text-zinc-200 whitespace-pre-wrap leading-relaxed">{msg.content}</p>
                  </div>
                ))}
              </div>
            ) : (
              <>
                {currentExample.instruction && (
                  <div>
                    <p className="text-[10px] font-semibold uppercase tracking-wide text-zinc-400 mb-1">Instruction</p>
                    <p className="text-sm text-zinc-700 dark:text-zinc-200">{currentExample.instruction}</p>
                  </div>
                )}
                {currentExample.input && (
                  <div>
                    <p className="text-[10px] font-semibold uppercase tracking-wide text-zinc-400 mb-1">Input</p>
                    <CodeBlock code={currentExample.input} />
                  </div>
                )}
                {currentExample.output && (
                  <div>
                    <p className="text-[10px] font-semibold uppercase tracking-wide text-emerald-600 dark:text-emerald-400 mb-1">Output</p>
                    <CodeBlock code={currentExample.output} tint="emerald" />
                  </div>
                )}
              </>
            )}
          </div>

          {/* Action row */}
          <div className="flex items-center justify-between mt-4">
            <div className="flex gap-2">
              <button
                onClick={handleApprove}
                disabled={isActioning}
                className="flex items-center gap-2 px-4 py-2 text-sm font-medium bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg disabled:opacity-50 transition-colors"
              >
                <ThumbsUp size={14} />
                Approve
              </button>
              <button
                onClick={handleReject}
                disabled={isActioning}
                className="flex items-center gap-2 px-4 py-2 text-sm font-medium bg-zinc-700 hover:bg-zinc-800 dark:bg-zinc-600 dark:hover:bg-zinc-500 text-white rounded-lg disabled:opacity-50 transition-colors"
              >
                <ThumbsDown size={14} />
                Reject
              </button>
            </div>
            <div className="flex items-center gap-4">
              {actionMsg && (
                <span className={`text-xs font-medium ${actionMsg.startsWith('✓') ? 'text-emerald-600 dark:text-emerald-400' : actionMsg.startsWith('✗') ? 'text-zinc-500 dark:text-zinc-400' : 'text-red-400'}`}>
                  {actionMsg}
                </span>
              )}
              <div className="text-xs text-zinc-400 dark:text-zinc-500 flex gap-3">
                <span className="text-emerald-600 dark:text-emerald-400 font-medium">👍 {approvedCount}</span>
                <span className="text-zinc-500 font-medium">👎 {rejectedCount}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
