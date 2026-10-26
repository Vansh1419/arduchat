import { useRef, useState } from "react";
import type { Session } from "./types";

type Props = {
  sessions: Session[];
  activeId: string | null;
  open: boolean;
  onClose: () => void;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  onRename: (id: string, title: string) => void;
  onExport: () => void;
  onImport: (file: File) => void;
};

export default function Sidebar(p: Props) {
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);

  function finishRename(id: string) {
    p.onRename(id, draft);
    setEditing(null);
  }

  return (
    <>
      {p.open && <div className="fixed inset-0 z-10 bg-black/30 md:hidden" onClick={p.onClose} />}
      <aside
        className={`fixed inset-y-0 left-0 z-20 flex w-72 flex-col border-r border-slate-200 bg-slate-50 transition-transform md:static md:translate-x-0 ${
          p.open ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="p-3">
          <button className="w-full rounded bg-sky-700 px-3 py-2 text-sm font-medium text-white hover:bg-sky-800" onClick={p.onNew}>
            + New chat
          </button>
        </div>
        <ul className="flex-1 overflow-y-auto px-2">
          {p.sessions.length === 0 && <li className="px-2 py-3 text-sm text-slate-500">No chats yet. Your chats are stored only in this browser.</li>}
          {p.sessions.map((s) => (
            <li key={s.id} className={`group flex items-center gap-1 rounded px-2 py-1.5 ${s.id === p.activeId ? "bg-sky-100" : "hover:bg-slate-200"}`}>
              {editing === s.id ? (
                <input
                  autoFocus
                  className="min-w-0 flex-1 rounded border border-slate-300 px-1 text-sm"
                  value={draft}
                  maxLength={80}
                  onChange={(e) => setDraft(e.target.value)}
                  onBlur={() => finishRename(s.id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") finishRename(s.id);
                    if (e.key === "Escape") setEditing(null);
                  }}
                />
              ) : (
                <button className="min-w-0 flex-1 truncate text-left text-sm" onClick={() => p.onSelect(s.id)}>
                  {s.title}
                </button>
              )}
              <button
                className="px-1 text-xs text-slate-500 hover:text-slate-900 md:invisible md:group-hover:visible"
                aria-label={`Rename ${s.title}`}
                onClick={() => {
                  setDraft(s.title);
                  setEditing(s.id);
                }}
              >
                ✎
              </button>
              <button
                className="px-1 text-xs text-slate-500 hover:text-red-700 md:invisible md:group-hover:visible"
                aria-label={`Delete ${s.title}`}
                onClick={() => window.confirm(`Delete "${s.title}"? This cannot be undone.`) && p.onDelete(s.id)}
              >
                🗑
              </button>
            </li>
          ))}
        </ul>
        <div className="flex gap-2 border-t border-slate-200 p-3 text-sm">
          <button className="flex-1 rounded border border-slate-300 px-2 py-1 hover:bg-slate-200" onClick={p.onExport} disabled={p.sessions.length === 0}>
            Export
          </button>
          <button className="flex-1 rounded border border-slate-300 px-2 py-1 hover:bg-slate-200" onClick={() => fileInput.current?.click()}>
            Import
          </button>
          <input
            ref={fileInput}
            type="file"
            accept="application/json"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) p.onImport(file);
              e.target.value = "";
            }}
          />
        </div>
      </aside>
    </>
  );
}
