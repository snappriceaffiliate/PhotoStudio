import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// base './' makes the built files work from any address or folder, for example
// https://example.com/copy/ or a plain static file server on localhost.
export default defineConfig({
  plugins: [react()],
  base: './',
  server: { host: true, port: 5180 },
  build: { outDir: 'dist' },
});
