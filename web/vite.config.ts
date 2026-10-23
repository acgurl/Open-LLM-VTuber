import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const backend = 'http://127.0.0.1:12393';
const backendWs = 'ws://127.0.0.1:12393';

export default defineConfig({
  base: './',
  plugins: [react()],
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 4096,
  },
  server: {
    port: 5173,
    proxy: {
      '/client-ws': { target: backendWs, ws: true, changeOrigin: false },
      '/audio-ws': { target: backendWs, ws: true, changeOrigin: false },
      '/tts-ws': { target: backendWs, ws: true, changeOrigin: false },
      '/api': backend,
      '/auth': backend,
      '/asr': backend,
      '/healthz': backend,
      '/live2d-models': backend,
      '/bg': backend,
      '/avatars': backend,
      '/cache': backend,
    },
  },
});
