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
    <form className="login" onSubmit={submit}>
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

const MODE_LABEL = { claude: "Written by Claude, checked against sources", extractive: "Quoted from your notes", abstain: "No answer" };

function AnswerText({ text, active, onRef }: { text: string; active: number | null; onRef: (r: number | null) => void }) {
  return (
    <p className="answer-text">
      {text.split(/(\[\d+\])/).map((part, i) => {
        const m = part.match(/^\[(\d+)\]$/);
        if (!m) return <span key={i}>{part}</span>;
        const ref = Number(m[1]);
        return (
          <button key={i} type="button" className={ref === active ? "ref on" : "ref"} aria-label={`Citation ${ref}`}
            onMouseEnter={() => onRef(ref)} onMouseLeave={() => onRef(null)} onFocus={() => onRef(ref)} onBlur={() => onRef(null)}>
            {ref}
          </button>
        );
      })}
    </p>
  );
}

function AskTab({ guard }: { guard: ReturnType<typeof useGuarded> }) {
  const [q, setQ] = useState("");
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [active, setActive] = useState<number | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    const { data, error } = await guard(() => api.ask(q));
    setBusy(false);
    setError(error ?? "");
    if (data) setAnswer(data);
  }

  return (
    <section>
      <form onSubmit={submit} className="ask">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask anything your notes can answer" required minLength={3} />
        <button type="submit" disabled={busy}>{busy ? "Reading" : "Ask"}</button>
      </form>
      {error && <p className="error">{error}</p>}
      {answer && (
        <div className="page">
          <div className="body">
            <p className={`stamp ${answer.mode}`}>{MODE_LABEL[answer.mode]}</p>
            {answer.answered
              ? <AnswerText text={answer.text} active={active} onRef={setActive} />
              : <p className="answer-text quiet">{answer.text}</p>}
            {answer.fallback_reason && <p className="fine">Claude's draft was not used: <code>{answer.fallback_reason}</code></p>}
          </div>
          {answer.citations.length > 0 && (
            <ol className="margin">
              {answer.citations.map((c) => (
                <li key={c.ref} className={c.ref === active ? "on" : ""} onMouseEnter={() => setActive(c.ref)} onMouseLeave={() => setActive(null)}>
                  <span className="num">{c.ref}</span>
                  <strong>{c.title}</strong>
                  <q>{c.sentence}</q>
                  <span className="signals">bm25 {c.bm25.toFixed(2)} · cos {c.dense.toFixed(2)}</span>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </section>
  );
}

function PracticeTab({ guard }: { guard: ReturnType<typeof useGuarded> }) {
  const [queue, setQueue] = useState<Question[]>([]);
  const [text, setText] = useState("");
  const [result, setResult] = useState<AttemptResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

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
    setBusy(true);
    const { data, error } = await guard(() => api.attempt(current.id, text));
    setBusy(false);
    setError(error ?? "");
    if (data) setResult(data);
  }

  function next() {
    setResult(null);
    setText("");
    void load(); // server decides what is due next; the client keeps no schedule
  }

  if (error) return <p className="error">{error}</p>;
  if (!current) return <p className="answer-text quiet">Nothing due right now. Come back later.</p>;

  return (
    <section className="drill">
      <p className="kicker">{current.topic} · {queue.length} due</p>
      <h2>{current.prompt}</h2>
      {!result ? (
        <form onSubmit={submit}>
          <textarea rows={5} value={text} onChange={(e) => setText(e.target.value)} placeholder="Write your answer in your own words" required />
          <button type="submit" disabled={busy}>{busy ? "Marking" : "Hand it in"}</button>
        </form>
      ) : (
        <div className="marked">
          <p className="grade">{Math.round(result.score * 100)}<small>%</small></p>
          <ul className="points">
            {result.covered.map((label) => (
              <li key={label} className="hit"><strong>{label}</strong>
                {result.evidence[label] && <q>{result.evidence[label]}</q>}
              </li>
            ))}
            {result.missed.map((label) => (
              <li key={label} className="miss"><strong>{label}</strong>
                {result.rejected.includes(label) && <span className="fine">Claude claimed this, but its quote was not in your answer.</span>}
              </li>
            ))}
          </ul>
          <p className="fine">Marked by {result.grader === "claude" ? "Claude, with quotes verified in code" : "keyword rubric"}. Next review in {result.interval_days} day(s).</p>
          <button onClick={next}>Next question</button>
        </div>
      )}
    </section>
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
    <section>
      <form onSubmit={add} className="add-note">
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
    </section>
  );
}

function StatsTab({ guard }: { guard: ReturnType<typeof useGuarded> }) {
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    void guard(() => api.stats()).then(({ data, error }) => { setError(error ?? ""); if (data) setStats(data); });
  }, [guard]);
  if (error) return <p className="error">{error}</p>;
  if (!stats) return <p className="fine">Loading…</p>;
  return (
    <section>
      <dl className="tally">
        <div><dt>Attempts</dt><dd>{stats.total_attempts}</dd></div>
        <div><dt>Average</dt><dd>{Math.round(stats.average_score * 100)}%</dd></div>
        <div><dt>Due now</dt><dd>{stats.due_now}</dd></div>
      </dl>
      {stats.topics.length === 0 && <p className="answer-text quiet">No attempts yet. Your weak topics will show here.</p>}
      <ul className="bars">
        {stats.topics.map((t) => (
          <li key={t.topic} className={stats.weakest_topics.includes(t.topic) ? "weak" : ""}>
            <span>{t.topic}</span>
            <span className="track"><span className="fill" style={{ width: `${Math.round(t.average_score * 100)}%` }} /></span>
            <span className="signals">{Math.round(t.average_score * 100)}% · {t.attempts}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export default function App() {
  const [authed, setAuthed] = useState(Boolean(getToken()));
  const [tab, setTab] = useState<Tab>("ask");
  const logout = useCallback(() => { setToken(null); setAuthed(false); }, []);
  const guard = useGuarded(logout);

  if (!authed) return <main className="front"><h1>Cited Study<br />Assistant</h1><p className="lede">Answers from your own notes, with a source beside every sentence.</p><AuthForm onDone={() => setAuthed(true)} /></main>;

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
