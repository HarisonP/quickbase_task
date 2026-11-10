import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  // In Docker the backend is http://backend:8000 (set by compose.yaml); locally it's localhost.
  const env = loadEnv(mode, ".", "");

  return {
    plugins: [react()],
    server: {
      // The browser only talks to the Vite dev server; /api is forwarded to FastAPI.
      // Same origin for the browser, so no CORS setup is needed in the backend.
      proxy: { "/api": env.API_PROXY_TARGET ?? "http://localhost:8000" },
    },
  };
});
