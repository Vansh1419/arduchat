export type Source = { url: string; title: string };

export type Message = {
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  disclaimer?: string;
  refused?: string; // reason code from the server: "blocked" | "not_found"
  error?: string;
};

export type Session = {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  messages: Message[];
};
