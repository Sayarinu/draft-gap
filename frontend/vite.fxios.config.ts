import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  build: {
    target: ["es2020", "firefox90", "safari15", "chrome90", "ios15"],
    cssTarget: "safari14",
    minify: "terser",
    emptyOutDir: false,
    copyPublicDir: false,
    rollupOptions: {
      input: path.resolve(__dirname, "src/main.tsx"),
      output: {
        format: "iife",
        name: "DraftGapFxios",
        inlineDynamicImports: true,
        entryFileNames: "assets/draft-gap-fxios.js",
        assetFileNames: "assets/draft-gap-fxios[extname]",
      },
    },
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
