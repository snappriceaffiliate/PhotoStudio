import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// The Django API runs on port 8000 locally, or as the "web" service inside Docker Compose.
const apiTarget = process.env.VITE_API_TARGET ?? 'http://localhost:8000';

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: { '/api': apiTarget },
  },
  build: {
    // Django collects this folder as static files in the production image.
    outDir: 'dist',
    manifest: true,
  },
  worker: { format: 'es' },
});
