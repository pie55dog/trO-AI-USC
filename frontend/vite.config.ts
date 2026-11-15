/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// With VITE_API_URL=/api the app talks to the backend through this server, so a
// phone only needs to reach one address (see scripts/local-server.sh).
const apiProxy = {
  target: "http://127.0.0.1:8000",
  changeOrigin: true,
  rewrite: (path: string) => path.replace(/^\/api/, ""),
};

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Listen on the network too, so a phone on the same Wi-Fi/hotspot can open it.
  server: { host: true, port: 5173, proxy: { "/api": apiProxy } },
  preview: { host: true, proxy: { "/api": apiProxy } },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
  },
});
