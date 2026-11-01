export type Citation = { ref: number; note_id: string; title: string; sentence: string; score: number };
export type Answer = { question: string; answered: boolean; text: string; citations: Citation[] };
export type Note = { id: number; title: string; text: string; shared: boolean };
export type Question = { id: number; topic: string; prompt: string; shared: boolean };
export type AttemptResult = {
  attempt_id: number; score: number; covered: string[]; missed: string[];
  feedback: string; interval_days: number; next_due_at: string;
};
export type Stats = {
  total_attempts: number; average_score: number; due_now: number;
  topics: { topic: string; attempts: number; average_score: number }[];
  weakest_topics: string[];
};

const TOKEN_KEY = "csa_token";

export const getToken = () => localStorage.getItem(TOKEN_KEY);
export const setToken = (t: string | null) =>
  t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY);

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`/api${path}`, { ...init, headers });
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    // FastAPI returns {detail: string} or, for validation errors, {detail: [...]}.
    const detail = typeof data.detail === "string" ? data.detail : "Request failed";
    throw new ApiError(res.status, detail);
  }
  return data as T;
}

const post = <T,>(path: string, body: unknown) =>
  request<T>(path, { method: "POST", body: JSON.stringify(body) });

export const api = {
  register: (email: string, password: string) => post("/auth/register", { email, password }),
  login: (email: string, password: string) =>
    post<{ access_token: string }>("/auth/login", { email, password }),
  ask: (question: string) => post<Answer>("/ask", { question }),
  notes: () => request<Note[]>("/notes"),
  addNote: (title: string, text: string) => post<Note>("/notes", { title, text }),
  deleteNote: (id: number) => request<void>(`/notes/${id}`, { method: "DELETE" }),
  due: () => request<Question[]>("/review/due?limit=20"),
  attempt: (id: number, answer: string) => post<AttemptResult>(`/questions/${id}/attempts`, { answer }),
  stats: () => request<Stats>("/stats"),
};
