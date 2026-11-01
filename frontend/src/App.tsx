import { FormEvent, useCallback, useEffect, useState } from "react";
import { Answer, ApiError, AttemptResult, Note, Question, Stats, api, getToken, setToken } from "./api";

type Tab = "ask" | "practice" | "notes" | "stats";

function useGuarded(onAuthFail: () => void) {
  // Any 401 from the API means the token is gone or expired: drop back to login.
  return useCallback(
    async <T,>(fn: () => Promise<T>): Promise<{ data?: T; error?: string }> => {
      try {
        return { data: await fn() };
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) onAuthFail();
        return { error: e instanceof Error ? e.message : "Something went wrong" };
      }
    },
    [onAuthFail],
  );
}

function AuthForm({ onDone }: { onDone: () => void }) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      if (mode === "register") await api.register(email, password);
      const { access_token } = await api.login(email, password);
      setToken(access_token);
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    }
  }

  return (
    <form className="card narrow" onSubmit={submit}>
      <h2>{mode === "login" ? "Log in" : "Create account"}</h2>
      <input type="email" placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} required />
      <input type="password" placeholder="Password (min 8 characters)" value={password}
        onChange={(e) => setPassword(e.target.value)} minLength={8} required />
      {error && <p className="error">{error}</p>}
      <button type="submit">{mode === "login" ? "Log in" : "Register"}</button>
      <button type="button" className="link" onClick={() => setMode(mode === "login" ? "register" : "login")}>
        {mode === "login" ? "Need an account? Register" : "Have an account? Log in"}
      </button>
    </form>
  );
}

function AskTab({ guard }: { guard: ReturnType<typeof useGuarded> }) {
  const [q, setQ] = useState("");
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [error, setError] = useState("");

  async function submit(e: FormEvent) {
    e.preventDefault();
    const { data, error } = await guard(() => api.ask(q));
    setError(error ?? "");
    if (data) setAnswer(data);
  }

  return (
    <div className="card">
      <form onSubmit={submit} className="row">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask a question about your notes" required />
        <button type="submit">Ask</button>
      </form>
      {error && <p className="error">{error}</p>}
      {answer && (
        <div className={answer.answered ? "answer" : "answer muted"}>
          <p>{answer.text}</p>
          {answer.citations.length > 0 && (
            <ol className="citations">
              {answer.citations.map((c) => (
                <li key={c.ref}>
                  <strong>{c.title}</strong> <span className="muted">(score {c.score})</span>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </div>
  );
}

function PracticeTab({ guard }: { guard: ReturnType<typeof useGuarded> }) {
  const [queue, setQueue] = useState<Question[]>([]);
  const [text, setText] = useState("");
  const [result, setResult] = useState<AttemptResult | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    const { data, error } = await guard(() => api.due());
    setError(error ?? "");
    if (data) setQueue(data);
  }, [guard]);
  useEffect(() => { void load(); }, [load]);

  const current = queue[0];

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!current) return;
    const { data, error } = await guard(() => api.attempt(current.id, text));
    setError(error ?? "");
    if (data) setResult(data);
  }

  function next() {
    setResult(null);
    setText("");
    void load(); // server decides what is due next; the client keeps no schedule
  }

  if (error) return <div className="card"><p className="error">{error}</p></div>;
  if (!current) return <div className="card"><p>Nothing due right now. Come back later.</p></div>;

  return (
    <div className="card">
      <p className="muted">{current.topic} · {queue.length} due</p>
      <h3>{current.prompt}</h3>
      {!result ? (
        <form onSubmit={submit}>
          <textarea rows={4} value={text} onChange={(e) => setText(e.target.value)} required />
          <button type="submit">Submit answer</button>
        </form>
      ) : (
        <div>
          <p><strong>Score {Math.round(result.score * 100)}%</strong> · {result.feedback}</p>
          <p className="muted">Next review in {result.interval_days} day(s).</p>
          <button onClick={next}>Next question</button>
        </div>
      )}
    </div>
  );
}

function NotesTab({ guard }: { guard: ReturnType<typeof useGuarded> }) {
  const [notes, setNotes] = useState<Note[]>([]);
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    const { data, error } = await guard(() => api.notes());
    setError(error ?? "");
    if (data) setNotes(data);
  }, [guard]);
  useEffect(() => { void load(); }, [load]);

  async function add(e: FormEvent) {
    e.preventDefault();
    const { error } = await guard(() => api.addNote(title, text));
    setError(error ?? "");
    if (!error) { setTitle(""); setText(""); void load(); }
  }

  return (
    <div className="card">
      <form onSubmit={add}>
        <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Title" required />
        <textarea rows={3} value={text} onChange={(e) => setText(e.target.value)}
          placeholder="Your note (at least 10 characters)" required minLength={10} />
        <button type="submit">Add private note</button>
      </form>
      {error && <p className="error">{error}</p>}
      <ul className="notes">
        {notes.map((n) => (
          <li key={n.id}>
            <strong>{n.title}</strong> {n.shared && <span className="tag">shared</span>}
            <p className="muted">{n.text}</p>
            {!n.shared && (
              <button className="link" onClick={async () => { await guard(() => api.deleteNote(n.id)); void load(); }}>
                Delete
              </button>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function StatsTab({ guard }: { guard: ReturnType<typeof useGuarded> }) {
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    void guard(() => api.stats()).then(({ data, error }) => { setError(error ?? ""); if (data) setStats(data); });
  }, [guard]);
  if (error) return <div className="card"><p className="error">{error}</p></div>;
  if (!stats) return <div className="card"><p>Loading…</p></div>;
  return (
    <div className="card">
      <p>{stats.total_attempts} attempts · average {Math.round(stats.average_score * 100)}% · {stats.due_now} due now</p>
      {stats.weakest_topics.length > 0 && <p>Weakest: <strong>{stats.weakest_topics.join(", ")}</strong></p>}
      <table>
        <thead><tr><th>Topic</th><th>Attempts</th><th>Average</th></tr></thead>
        <tbody>
          {stats.topics.map((t) => (
            <tr key={t.topic}><td>{t.topic}</td><td>{t.attempts}</td><td>{Math.round(t.average_score * 100)}%</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function App() {
  const [authed, setAuthed] = useState(Boolean(getToken()));
  const [tab, setTab] = useState<Tab>("ask");
  const logout = useCallback(() => { setToken(null); setAuthed(false); }, []);
  const guard = useGuarded(logout);

  if (!authed) return <main><h1>Cited Study Assistant</h1><AuthForm onDone={() => setAuthed(true)} /></main>;

  return (
    <main>
      <header>
        <h1>Cited Study Assistant</h1>
        <button className="link" onClick={logout}>Log out</button>
      </header>
      <nav>
        {(["ask", "practice", "notes", "stats"] as Tab[]).map((t) => (
          <button key={t} className={t === tab ? "active" : ""} onClick={() => setTab(t)}>{t}</button>
        ))}
      </nav>
      {tab === "ask" && <AskTab guard={guard} />}
      {tab === "practice" && <PracticeTab guard={guard} />}
      {tab === "notes" && <NotesTab guard={guard} />}
      {tab === "stats" && <StatsTab guard={guard} />}
    </main>
  );
}
