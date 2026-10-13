import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  define: {
    global: 'globalThis',
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      "/funding-api": {
        target: "http://127.0.0.1:8788",
        changeOrigin: true,
        rewrite: path =>
          path.replace(/^\/funding-api/, ""),
      },

      '/dev-signer': {
        target: 'http://127.0.0.1:8799',
        changeOrigin: true,
        rewrite: path =>
          path.replace(/^\/dev-signer/, ''),
      },
      '/solana-rpc': {
        target: 'http://127.0.0.1:8899',
        changeOrigin: true,
        rewrite: path =>
          path.replace(/^\/solana-rpc$/, '/'),
      },
      '/v1': {
        target: 'http://127.0.0.1:8787',
        changeOrigin: false,
      },
      '/health': {
        target: 'http://127.0.0.1:8787',
        changeOrigin: false,
      },
      '/openapi.json': {
        target: 'http://127.0.0.1:8787',
        changeOrigin: false,
      },
    },
  },
});
