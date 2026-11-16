import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// base './' makes the built files work from any address or folder, for example
// https://example.com/copy/ or a plain static file server on localhost.
export default defineConfig({
  plugins: [react()],
  base: './',
  // In development the page asks PickSnap's API (run by Docker Compose on port 8000) for an event's
  // selection; the studio's login cookie for localhost is shared across ports.
  server: { host: true, port: 5180, proxy: { '/api': process.env.VITE_API_TARGET ?? 'http://localhost:8000' } },
  build: { outDir: 'dist' },
});
