import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// In development the API is proxied, so the browser sees one origin. That keeps the
// SameSite=Strict refresh cookie working and avoids CORS entirely.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: { "/api": { target: process.env.VITE_API_TARGET || "http://localhost:8000", changeOrigin: false } },
  },
  preview: {
    port: 4173,
    proxy: { "/api": { target: process.env.VITE_API_TARGET || "http://localhost:8000", changeOrigin: false } },
  },
});
