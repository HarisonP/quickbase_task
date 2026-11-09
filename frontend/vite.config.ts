import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    // The browser only talks to the Vite dev server; /api is forwarded to FastAPI.
    // Same origin for the browser, so no CORS setup is needed in the backend.
    proxy: { "/api": "http://localhost:8000" },
  },
});
