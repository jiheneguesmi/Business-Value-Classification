// API client for the local Python backend (server.py)
// Configure via VITE_API_URL (defaults to http://127.0.0.1:8000)

export type Category = "ROI" | "Notoriete" | "Obligation" | "Description";
export type Mode = "rapide" | "expert";

export interface ApiDocument {
  id: string;
  name: string;
  client: string;
  date: string;
  mode: Mode;
  phrases: number;
  pages: number;
  costEur: number;
  durationS: number;
  distribution: Record<Category, number>;
  dominant: Category;
  path?: string;
}

export interface ApiPhrase {
  id: string;
  phrase: string;
  document: string;
  categorie: Category;
  confidence: number;
  scores: { ROI: number; Notoriete: number; Obligation: number; Description: number };
  modeUsed: Mode;
  costEur?: number;
  durationS?: number;
  responses?: Record<string, string>;
}

export interface DashboardPayload {
  corpusStats: {
    documents: number;
    phrases: number;
    models: number;
    questions: number;
    clients: number;
    totalCostEur: number;
  };
  distribution: Record<Category, number>;
  recentDocuments: ApiDocument[];
}

export interface ResultsPayload {
  document: ApiDocument | null;
  phrases: ApiPhrase[];
}

export interface SummaryPayload {
  document: ApiDocument | null;
  dominant?: Category;
  dominantPct?: number;
  weak?: Category;
  weakPct?: number;
  keyPhrases?: ApiPhrase[];
  recommendations?: string[];
}

export interface AnalyzeResponse {
  status: string;
  message: string;
  document: ApiDocument;
  phrases: ApiPhrase[];
}

export const API_BASE: string =
  (typeof import.meta !== "undefined" && (import.meta as any).env?.VITE_API_URL) ||
  "http://127.0.0.1:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init);
  if (!res.ok) {
    let detail = "";
    try {
      const j = await res.json();
      detail = j?.error || JSON.stringify(j);
    } catch {
      try {
        detail = await res.text();
      } catch {
        /* ignore */
      }
    }
    throw new Error(`API ${path} → ${res.status} ${detail}`.trim());
  }
  return (await res.json()) as T;
}

export const api = {
  dashboard: () => request<DashboardPayload>("/api/dashboard"),
  documents: () => request<{ documents: ApiDocument[] }>("/api/documents"),
  results: (documentId: string) =>
    request<ResultsPayload>(`/api/results?documentId=${encodeURIComponent(documentId)}`),
  summary: (documentId: string) =>
    request<SummaryPayload>(`/api/summary?documentId=${encodeURIComponent(documentId)}`),
  analyze: async (file: File, mode: Mode, client?: string): Promise<AnalyzeResponse> => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("mode", mode);
    if (client && client.trim()) fd.append("client", client.trim());
    const res = await fetch(`${API_BASE}/api/analyze`, { method: "POST", body: fd });
    if (!res.ok) {
      let detail = "";
      try {
        detail = (await res.json())?.error ?? "";
      } catch {
        /* ignore */
      }
      throw new Error(`Analyse échouée (${res.status}) ${detail}`.trim());
    }
    return (await res.json()) as AnalyzeResponse;
  },
};
