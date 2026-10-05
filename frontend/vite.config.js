import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

// base './' keeps the built site working from any sub-path (GitHub Pages, S3, a folder...).
export default defineConfig(({ mode }) => {
  // Only the dev server reads this; in production nginx does the same-origin proxying
  // (docker/frontend/nginx.conf), which is why src/lib/api.js needs no env var.
  const env = loadEnv(mode, process.cwd(), 'VITE_');
  const target = env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000';
  const isProd = mode === 'production';

  return {
    base: './',
    plugins: [react()],
    server: {
      host: '0.0.0.0',
      port: 5173,
      strictPort: true,
      // Proxying makes the dev origin identical to the deployed one, so the frontend
      // code path that works in the container is the same one exercised locally:
      // no CORS preflight, and the WebSocket upgrade works without a special case.
      proxy: {
        '/api': { target, changeOrigin: true },
        '/ws': { target, ws: true, changeOrigin: true },
        '/healthz': { target, changeOrigin: true },
      },
    },
    build: {
      target: 'es2020',
      cssCodeSplit: true,
      cssMinify: isProd,
      sourcemap: false,
      reportCompressedSize: false,
      assetsInlineLimit: 4096,
      chunkSizeWarningLimit: 900,
      rollupOptions: {
        output: {
          // three (~512 KB) and react (~140 KB) change far less often than app
          // code. Splitting them into stable vendor chunks means repeat visitors
          // re-download only the app chunk after a deploy — the vendors come
          // from the browser cache (backend serves them immutable for a year).
          manualChunks: {
            three: ['three'],
            vendor: ['react', 'react-dom'],
          },
        },
      },
    },
  };
});
