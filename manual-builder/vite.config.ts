import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Pure static SPA. All project I/O happens in the browser via the File System
// Access API (see src/fs/*), so there is no backend to configure.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
  },
});
