import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { readFileSync } from 'node:fs';

export default defineConfig(({ mode }) => {
  if (!['development', 'production', 'localnet', 'devnet'].includes(mode))
    throw new Error('MAINNET_DISABLED');
  return {
  // Vite otherwise copies public/idl/localnet-idl.json into the Devnet artifact.
  publicDir: mode === 'devnet' ? false : 'public',
  // Separate entry graph: the Devnet build never imports wallet or transaction modules.
  plugins: mode === 'devnet' ? [react(), {
    name: 'conatus-devnet-entry',
    generateBundle() {
      for (const fileName of ['idl/devnet-idl.json', 'images/conatus-physical-ai.jpg']) {
        this.emitFile({
          type: 'asset',
          fileName,
          source: readFileSync(new URL(`./public/${fileName}`, import.meta.url)),
        });
      }
    },
    transformIndexHtml: {
      order: 'pre',
      handler(html: string) {
        if (!html.includes('/src/main.ts')) throw new Error('ENTRY_NOT_FOUND');
        return html.replace('/src/main.ts', '/src/devnet-bootstrap.tsx');
      },
    },
  }] : [react()],
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
  };
});
