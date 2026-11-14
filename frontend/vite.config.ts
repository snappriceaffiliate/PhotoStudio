import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// The Django API runs on port 8000 locally, or as the "web" service inside Docker Compose.
const apiTarget = process.env.VITE_API_TARGET ?? 'http://localhost:8000';

export default defineConfig(({ command }) => ({
  plugins: [react()],
  // In production Django serves the built files from /static/ (WhiteNoise).
  base: command === 'build' ? '/static/' : '/',
  server: {
    host: true,
    port: 5173,
    // Django admin and its static files are reachable from the dev server too.
    proxy: { '/api': apiTarget, '/admin': apiTarget, '/static': apiTarget },
  },
  build: {
    // Django collects this folder as static files in the production image.
    outDir: 'dist',
    manifest: true,
  },
  worker: { format: 'es' },
}));
