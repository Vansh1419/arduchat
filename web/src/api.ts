import type { Source } from "./types";

// Server limits (app/chat.py): history turn <= 4000 chars, <= 10 turns.
const MAX_TURN_CHARS = 4000;
const MAX_TURNS = 10;

export type Turn = { role: "user" | "assistant"; content: string };

export type StreamHandlers = {
  onSources: (sources: Source[]) => void;
  onToken: (token: string) => void;
  onReplace: (text: string) => void;
  onDisclaimer: (text: string) => void;
  onRefused: (reason: string) => void;
  onError: (message: string) => void;
};

export function toHistory(turns: Turn[]): Turn[] {
  return turns.slice(-MAX_TURNS).map((t) => ({ role: t.role, content: t.content.slice(0, MAX_TURN_CHARS) }));
}

function readableWait(seconds: number): string {
  if (seconds < 90) return `${seconds} seconds`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} minutes`;
  return `${Math.round(seconds / 3600)} hours`;
}

async function httpErrorMessage(res: Response): Promise<string> {
  let detail = "";
  try {
    const body = await res.json();
    detail = typeof body.detail === "string" ? body.detail : "";
  } catch {
    /* body was not JSON */
  }
  const wait = res.headers.get("Retry-After");
  if (res.status === 429 || res.status === 503) {
    return `${detail || "Too many requests."}${wait ? ` Try again in about ${readableWait(Number(wait))}.` : ""}`;
  }
  return detail || `Request failed (${res.status}).`;
}

/** POSTs the question and dispatches the server's SSE events (see app/chat.py). */
export async function streamChat(message: string, history: Turn[], h: StreamHandlers): Promise<void> {
  let res: Response;
  try {
    res = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, history: toHistory(history) }),
    });
  } catch {
    h.onError("Could not reach the server.");
    return;
  }
  if (!res.ok || !res.body) {
    h.onError(await httpErrorMessage(res));
    return;
  }

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read().catch(() => ({ value: undefined, done: true }));
    if (done) break;
    buffer += value;
    let end: number;
    while ((end = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      const event = /^event: (.*)$/m.exec(block)?.[1];
      const data = /^data: (.*)$/m.exec(block)?.[1];
      if (!event || data === undefined) continue;
      const payload = JSON.parse(data);
      if (event === "sources") h.onSources(payload);
      else if (event === "token") h.onToken(payload);
      else if (event === "replace") h.onReplace(payload);
      else if (event === "disclaimer") h.onDisclaimer(payload);
      else if (event === "refused") h.onRefused(payload);
      else if (event === "error") h.onError("The answer was interrupted. Please try again.");
    }
  }
}
