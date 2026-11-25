import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  server: {
    host: "localhost",
    port: 5273,
    strictPort: true,
    proxy: {
      "/api": {
        target: process.env.REVIEW_DEV_API_URL ?? "http://127.0.0.1:8780",
        changeOrigin: false,
      },
      "/health": {
        target: process.env.REVIEW_DEV_API_URL ?? "http://127.0.0.1:8780",
        changeOrigin: false,
      },
    },
  },
});
