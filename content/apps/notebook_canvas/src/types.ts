export interface Notebook {
  id: string;
  name: string;
  description: string;
  created_at: string;
  updated_at: string;
}

export interface Source {
  id: string;
  notebook_id: string;
  title: string;
  content: string;
  type: 'text' | 'url' | 'file';
  url?: string;
  created_at: string;
}

export interface Note {
  id: string;
  notebook_id: string;
  title: string;
  content: string;
  created_at: string;
  updated_at: string;
}

export interface Workflow {
  id: string;
  notebook_id: string;
  name: string;
  nodes: string; // JSON string
  edges: string; // JSON string
  created_at: string;
  updated_at: string;
}

export type ViewMode = 'chat' | 'note' | 'workflow' | 'source' | 'data' | 'nexus' | 'nlm' | 'aistudio' | 'accounts' | 'training';

export interface NexusEntry {
  id?: string;
  title: string;
  content: string;
  content_type?: string;
  category?: string;
  tags?: string[];
  created_at?: string;
}

export interface NLMNotebook {
  id: string;
  name: string;
  description?: string;
  source_count?: number;
  topics?: string[];
}

export interface GoogleAccount {
  id: string;
  cookie_count: number;
  rate_limited: boolean;
  last_used?: string;
  requests_today?: number;
}

export interface TrainingExample {
  id?: string;
  prompt: string;
  response: string;
  rating?: 'positive' | 'negative' | null;
  source?: string;
  captured_at?: string;
}
