import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import stringPlugin from 'vite-plugin-string';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_');
  const target = env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000';
  const isProd = mode === 'production';

  return {
    base: './',
    plugins: [
      react(),
      stringPlugin({ include: ['**/*.glsl', '**/*.vert', '**/*.frag', '**/*.vs', '**/*.fs'] }),
    ],
    server: { host: '0.0.0.0', port: 5173, strictPort: true, proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true }, '/ws': { target: 'http://127.0.0.1:8000', ws: true, changeOrigin: true }, '/healthz': { target: 'http://127.0.0.1:8000', changeOrigin: true } } },
    build: { target: 'es2020', cssCodeSplit: true, cssMinify: true, sourcemap: false, reportCompressedSize: false, assetsInlineLimit: 4096, chunkSizeWarningLimit: 900, rollupOptions: { output: { manualChunks: { three: ['three'], vendor: ['react', 'react-dom'] } } } },
  };
});