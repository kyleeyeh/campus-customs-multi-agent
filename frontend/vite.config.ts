import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The desk runs on 5173, which is the origin backend/main.py allows through CORS.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true, open: true },
});
