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

export type ViewMode = 'chat' | 'note' | 'workflow' | 'source' | 'data' | 'nexus' | 'nlm' | 'aistudio' | 'accounts' | 'training' | 'compute' | 'har' | 'rpc' | 'copilot';

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

// ── Compute Panel Types ─────────────────────────────────────────────────────

export interface ComputeAccount {
  name: string;
  tier: 'free' | 'pro' | 'unknown';
  services: string[];
  hardware: string[];
  usage: Record<string, number>;
  limits: Record<string, number>;
}

export interface TunnelSession {
  id: string;
  account_name: string;
  tunnel_url: string;
  tunnel_type: string;
  hardware: string;
  started_at: number;
  healthy: boolean;
}

export interface JITConfig {
  max_session_minutes: number;
  idle_timeout_minutes: number;
  human_delays: boolean;
  min_delay_s: number;
  max_delay_s: number;
}

// ── HAR Explorer Types ──────────────────────────────────────────────────────

export interface HARFile {
  name: string;
  size_mb: number;
  path: string;
}

export interface HAREntry {
  url: string;
  method: string;
  status: number;
  mime_type: string;
  size: number;
  time_ms: number;
  send_time_ms: number;
  wait_time_ms: number;
  request_headers: Record<string, string>;
  response_headers: Record<string, string>;
  request_cookies: Array<{ name: string; value: string }>;
  response_cookies: Array<{ name: string; value: string }>;
  request_body: string;
  response_body: string;
}

// ── RPC Explorer Types ──────────────────────────────────────────────────────

export interface RpcRequest {
  id: string;
  url: string;
  method: string;
  account_name: string;
  headers: Record<string, string>;
  body: string;
  content_type: string;
  label?: string;
}

export interface RpcHistoryEntry {
  id: string;
  request: RpcRequest;
  response: {
    status: number;
    body: string;
    headers: Record<string, string>;
    latency_ms: number;
  };
  timestamp: number;
}

export interface RpcTemplate {
  label: string;
  url: string;
  method: string;
  content_type: string;
  body: string;
}

