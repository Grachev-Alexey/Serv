import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// В деве фронт на :5173 проксирует /api и /hls на бэкенд :8000,
// поэтому cookie-сессии работают как на одном origin (как в проде за Nginx).
export default defineConfig({
  plugins: [react()],
  server: {
    host: true, // слушать на всех интерфейсах (IPv4 + доступ с других устройств в сети)
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/hls": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
});
