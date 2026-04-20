import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

// Vite config for NeoMind web frontend.
// - `@/` alias → src/  (shadcn convention)
// - Dev proxy: /api /openbb /audit → 127.0.0.1:8001 so browser sees one origin
// - Prod build: output lands in `dist/`, FastAPI serves it
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8001',
      '/openbb': 'http://127.0.0.1:8001',
      '/audit': 'http://127.0.0.1:8001',
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
