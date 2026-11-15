/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv, type Plugin } from "vite";

/**
 * Content-Security-Policy for production builds (GitHub Pages can't send
 * headers, so it goes in a <meta> tag). Scripts only from this site, network
 * calls only to this site and the trO API, no plugins, no <base> tricks: an
 * injected script couldn't run or send a login token anywhere. Left off in
 * dev, where Vite needs inline scripts for hot reload.
 */
function contentSecurityPolicy(apiUrl: string): Plugin {
  let api = "";
  try {
    api = apiUrl && /^https?:/.test(apiUrl) ? new URL(apiUrl).origin : "";
  } catch {
    api = "";
  }
  const policy = [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com",
    `img-src 'self' data: blob: https: ${api}`.trim(),
    `connect-src 'self' ${api}`.trim(),
    "media-src 'self' blob:",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
  ].join("; ");
  return {
    name: "tro-csp",
    apply: "build",
    transformIndexHtml: (html) =>
      html.replace("<head>", `<head>\n    <meta http-equiv="Content-Security-Policy" content="${policy}" />`),
  };
}

// With VITE_API_URL=/api the app talks to the backend through this server, so a
// phone only needs to reach one address (see scripts/local-server.sh).
const apiProxy = {
  target: "http://127.0.0.1:8000",
  changeOrigin: true,
  rewrite: (path: string) => path.replace(/^\/api/, ""),
};

export default defineConfig(({ mode }) => ({
  plugins: [react(), tailwindcss(), contentSecurityPolicy(loadEnv(mode, process.cwd(), "VITE_").VITE_API_URL ?? process.env.VITE_API_URL ?? "")],
  // Listen on the network too, so a phone on the same Wi-Fi/hotspot can open it.
  server: { host: true, port: 5173, proxy: { "/api": apiProxy } },
  preview: { host: true, proxy: { "/api": apiProxy } },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
  },
}));
