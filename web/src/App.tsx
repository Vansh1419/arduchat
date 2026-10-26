import { useRef, useState } from "react";
import { streamChat } from "./api";
import { loadSessions, parseSession, removeSession, saveSession } from "./storage";
import type { Message, Session } from "./types";
import Chat from "./Chat";
import Sidebar from "./Sidebar";

const TITLE_CHARS = 50;

export default function App() {
  const [sessions, setSessions] = useState<Session[]>(loadSessions);
  const [activeId, setActiveId] = useState<string | null>(() => loadSessions()[0]?.id ?? null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);

  // Source of truth for the streaming callbacks; every change goes through setAll so state and ref never diverge.
  const ref = useRef(sessions);
  function setAll(next: Session[]) {
    ref.current = next;
    setSessions(next);
  }

  const active = sessions.find((s) => s.id === activeId) ?? null;

  function persist(s: Session) {
    if (!saveSession(s)) setNotice("Your browser could not save this chat (storage full or blocked). Export your chats to keep them.");
  }

  /** Applies `change` to one session in state; saved only when `save` is set (not on every token). */
  function update(id: string, change: (s: Session) => Session, save = false) {
    const next = ref.current.map((s) => (s.id === id ? change(s) : s));
    setAll(next);
    const updated = next.find((s) => s.id === id);
    if (save && updated) persist(updated);
  }

  function newChat() {
    const now = Date.now();
    const s: Session = { id: crypto.randomUUID(), title: "New chat", createdAt: now, updatedAt: now, messages: [] };
    persist(s);
    setAll([s, ...ref.current]);
    setActiveId(s.id);
    setMenuOpen(false);
  }

  function deleteChat(id: string) {
    removeSession(id);
    const rest = ref.current.filter((s) => s.id !== id);
    setAll(rest);
    if (activeId === id) setActiveId(rest[0]?.id ?? null);
  }

  function renameChat(id: string, title: string) {
    update(id, (s) => ({ ...s, title: title.trim() || s.title }), true);
  }

  async function send(text: string) {
    let id = activeId;
    if (!id) {
      const now = Date.now();
      id = crypto.randomUUID();
      const s: Session = { id, title: "New chat", createdAt: now, updatedAt: now, messages: [] };
      setAll([s, ...ref.current]);
      setActiveId(id);
    }
    const chatId = id;
    const before = ref.current.find((s) => s.id === chatId)!.messages;
    const history = before.filter((m) => !m.refused && !m.error).map(({ role, content }) => ({ role, content }));

    const patchLast = (change: (m: Message) => Message) =>
      update(chatId, (s) => ({ ...s, messages: s.messages.map((m, i) => (i === s.messages.length - 1 ? change(m) : m)) }));

    update(chatId, (s) => ({
      ...s,
      title: s.messages.length === 0 ? text.slice(0, TITLE_CHARS) : s.title,
      updatedAt: Date.now(),
      messages: [...s.messages, { role: "user", content: text }, { role: "assistant", content: "" }],
    }));
    setBusy(true);
    await streamChat(text, history, {
      onSources: (sources) => patchLast((m) => ({ ...m, sources })),
      onToken: (t) => patchLast((m) => ({ ...m, content: m.content + t })),
      onReplace: (content) => patchLast((m) => ({ ...m, content })),
      onDisclaimer: (disclaimer) => patchLast((m) => ({ ...m, disclaimer })),
      onRefused: (refused) => patchLast((m) => ({ ...m, refused })),
      onError: (error) => patchLast((m) => ({ ...m, error })),
    });
    update(chatId, (s) => ({ ...s, updatedAt: Date.now() }), true);
    setBusy(false);
  }

  function exportChats() {
    const blob = new Blob([JSON.stringify({ version: 1, sessions: ref.current }, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `arduchat-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  async function importChats(file: File) {
    try {
      const data = JSON.parse(await file.text());
      const incoming = (Array.isArray(data.sessions) ? data.sessions : []).map(parseSession).filter((s: Session | null): s is Session => !!s);
      const known = new Set(ref.current.map((s) => s.id));
      const fresh = incoming.filter((s: Session) => !known.has(s.id));
      fresh.forEach(persist);
      const merged = [...ref.current, ...fresh].sort((a, b) => b.updatedAt - a.updatedAt);
      setAll(merged);
      setNotice(`Imported ${fresh.length} chat(s)${incoming.length > fresh.length ? `, skipped ${incoming.length - fresh.length} that already exist` : ""}.`);
    } catch {
      setNotice("That file is not a valid ArduChat export.");
    }
  }

  return (
    <div className="flex h-dvh bg-white text-slate-900">
      <Sidebar
        sessions={sessions}
        activeId={activeId}
        open={menuOpen}
        onClose={() => setMenuOpen(false)}
        onSelect={(id) => {
          setActiveId(id);
          setMenuOpen(false);
        }}
        onNew={newChat}
        onDelete={deleteChat}
        onRename={renameChat}
        onExport={exportChats}
        onImport={importChats}
      />
      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-slate-200 px-4 py-3">
          <button className="rounded border border-slate-300 px-2 py-1 text-sm md:hidden" onClick={() => setMenuOpen(true)} aria-label="Open chats">
            ☰
          </button>
          <h1 className="truncate font-semibold">{active?.title ?? "ArduChat"}</h1>
        </header>
        {notice && (
          <div className="flex items-start justify-between gap-3 bg-amber-50 px-4 py-2 text-sm text-amber-900" role="status">
            <span>{notice}</span>
            <button onClick={() => setNotice("")} aria-label="Dismiss">✕</button>
          </div>
        )}
        <Chat messages={active?.messages ?? []} busy={busy} onSend={send} />
      </main>
    </div>
  );
}
