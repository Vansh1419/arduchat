import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSanitize from "rehype-sanitize";
import type { Message } from "./types";

const MAX_MESSAGE_CHARS = 2000; // server limit (app/chat.py)

const isHttp = (url: string) => /^https?:\/\//i.test(url);

function Bubble({ m, streaming }: { m: Message; streaming: boolean }) {
  if (m.role === "user") {
    return (
      <div className="flex justify-end">
        <p className="max-w-[85%] whitespace-pre-wrap rounded-lg bg-sky-700 px-3 py-2 text-white">{m.content}</p>
      </div>
    );
  }
  return (
    <div className="max-w-[95%] md:max-w-[85%]">
      {m.content && (
        <div className={`prose prose-slate prose-sm max-w-none ${m.refused ? "italic text-slate-600" : ""}`}>
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            rehypePlugins={[rehypeSanitize]}
            components={{ a: ({ node: _node, ...props }) => <a {...props} target="_blank" rel="noopener noreferrer" /> }}
          >
            {m.content}
          </ReactMarkdown>
        </div>
      )}
      {streaming && !m.content && !m.error && <p className="text-sm text-slate-500">Thinking…</p>}
      {m.error && <p className="rounded bg-red-50 px-3 py-2 text-sm text-red-800" role="alert">{m.error}</p>}
      {m.disclaimer && <p className="mt-2 rounded bg-amber-50 px-3 py-2 text-sm text-amber-900">{m.disclaimer}</p>}
      {m.sources && m.sources.length > 0 && !m.refused && (
        <div className="mt-2 text-xs text-slate-600">
          Sources:{" "}
          {m.sources.filter((s) => isHttp(s.url)).map((s, i) => (
            <a key={s.url} className="underline" href={s.url} target="_blank" rel="noopener noreferrer">
              {i > 0 && ", "}
              {s.title || s.url}
            </a>
          ))}
        </div>
      )}
    </div>
  );
}

export default function Chat({ messages, busy, onSend }: { messages: Message[]; busy: boolean; onSend: (text: string) => void }) {
  const [text, setText] = useState("");
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [messages]);

  function submit() {
    const trimmed = text.trim();
    if (!trimmed || busy) return;
    onSend(trimmed);
    setText("");
  }

  return (
    <>
      <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4">
        {messages.length === 0 && (
          <p className="mx-auto mt-16 max-w-md text-center text-slate-500">
            Ask anything about ArduPilot Copter: flight modes, parameters, failsafes, setup. Answers come from the official documentation.
          </p>
        )}
        {messages.map((m, i) => (
          <Bubble key={i} m={m} streaming={busy && i === messages.length - 1} />
        ))}
        <div ref={bottom} />
      </div>
      <form
        className="flex gap-2 border-t border-slate-200 p-3"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <textarea
          className="min-h-11 flex-1 resize-none rounded border border-slate-300 px-3 py-2 focus:outline-sky-600"
          rows={1}
          maxLength={MAX_MESSAGE_CHARS}
          placeholder="Ask about ArduPilot Copter…"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
        />
        <button className="rounded bg-sky-700 px-4 py-2 font-medium text-white hover:bg-sky-800 disabled:opacity-50" disabled={busy || !text.trim()}>
          Send
        </button>
      </form>
    </>
  );
}
