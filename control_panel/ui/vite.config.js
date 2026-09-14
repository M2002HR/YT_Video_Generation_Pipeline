import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  // Keep prior hashed bundles so browser tabs that were already open during a
  // deploy can finish loading instead of requesting a deleted chunk.
  build: { outDir: "../dist", emptyOutDir: false },
});
