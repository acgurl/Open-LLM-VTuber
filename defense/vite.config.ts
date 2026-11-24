import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';
import { viteSingleFile } from 'vite-plugin-singlefile';

function devEntryRedirect(): Plugin {
  return {
    name: 'defense-dev-entry-redirect',
    configureServer(server) {
      server.middlewares.use((req, _res, next) => {
        if (req.url === '/' || req.url?.startsWith('/?')) {
          req.url = `/entry.html${req.url.slice(1)}`;
        }
        next();
      });
    },
  };
}

export default defineConfig(({ command, mode }) => ({
  base: './',
  plugins:
    command === 'build' && mode !== 'test'
      ? [react(), viteSingleFile({ outputFileName: 'index.html' })]
      : [react(), devEntryRedirect()],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      input: 'entry.html',
    },
  },
  server: {
    host: '127.0.0.1',
    port: 5179,
    strictPort: true,
  },
}));
