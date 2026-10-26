import type { Session } from "./types";

const PREFIX = "arduchat:session:";

/** All chats live in the user's browser: one localStorage key per session. */
export function loadSessions(): Session[] {
  const sessions: Session[] = [];
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (!key?.startsWith(PREFIX)) continue;
      const s = parseSession(localStorage.getItem(key));
      if (s) sessions.push(s);
    }
  } catch {
    /* storage unavailable (private mode / blocked) */
  }
  return sessions.sort((a, b) => b.updatedAt - a.updatedAt);
}

/** Returns false if the browser refused the write (quota exceeded, blocked storage). */
export function saveSession(s: Session): boolean {
  try {
    localStorage.setItem(PREFIX + s.id, JSON.stringify(s));
    return true;
  } catch {
    return false;
  }
}

export function removeSession(id: string) {
  try {
    localStorage.removeItem(PREFIX + id);
  } catch {
    /* nothing to remove */
  }
}

export function parseSession(raw: unknown): Session | null {
  try {
    const s = typeof raw === "string" ? JSON.parse(raw) : raw;
    if (
      s && typeof s.id === "string" && typeof s.title === "string" &&
      typeof s.createdAt === "number" && typeof s.updatedAt === "number" &&
      Array.isArray(s.messages) &&
      s.messages.every((m: any) => (m?.role === "user" || m?.role === "assistant") && typeof m.content === "string")
    ) {
      return s as Session;
    }
  } catch {
    /* corrupt entry */
  }
  return null;
}
