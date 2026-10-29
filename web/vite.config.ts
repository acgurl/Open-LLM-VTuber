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
    rollupOptions: {
      output: {
        // Live2D/pixi 与 React 单独成块：两者几乎不随业务代码变化，部署后回访只重下应用代码。
        manualChunks(id: string) {
          if (!id.includes('node_modules')) return;
          if (
            /node_modules[\\/](@pixi|pixi\.js|pixi-live2d-display-lipsyncpatch|earcut|ismobilejs|eventemitter3)[\\/]/.test(
              id,
            )
          ) {
            return 'live2d';
          }
          if (/node_modules[\\/](react|react-dom|scheduler)[\\/]/.test(id)) return 'react';
          return;
        },
      },
    },
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
