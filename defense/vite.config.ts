import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { viteSingleFile } from 'vite-plugin-singlefile';

export default defineConfig(({ command }) => ({
  base: './',
  plugins: command === 'build' ? [react(), viteSingleFile()] : [react()],
  server: {
    host: '127.0.0.1',
    port: 5179,
    strictPort: true,
  },
}));
