import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The dev server binds 0.0.0.0:5173 so it works inside Docker as well as locally.
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
  },
  preview: {
    host: true,
    port: 5173,
  },
});
