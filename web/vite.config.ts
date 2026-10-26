import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// In dev the API runs separately on :8000; in production FastAPI serves web/dist itself.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { proxy: { "/chat": "http://localhost:8000", "/health": "http://localhost:8000" } },
});
