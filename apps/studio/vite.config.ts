import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  base: "/studio/",
  define: {
    __BITTUNE_API_URL__: JSON.stringify("/api/v1"),
  },
  server: {
    port: 5174,
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
