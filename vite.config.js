import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// base './' keeps the built site working from any sub-path (GitHub Pages, S3, a folder...).
export default defineConfig({
  base: './',
  plugins: [react()],
  build: {
    chunkSizeWarningLimit: 900,
    rollupOptions: {
      output: {
        manualChunks: { three: ['three'] },
      },
    },
  },
});
