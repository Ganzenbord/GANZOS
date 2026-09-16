import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // De API draait apart; dit scheelt CORS-gedoe tijdens het bouwen.
    proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true } },
  },
  // Relatieve paden, want Electron laadt het bestand van schijf en niet van een server.
  base: './',
  build: { outDir: 'dist', sourcemap: false },
})
