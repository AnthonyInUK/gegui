import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 前端 5173，后端 FastAPI 8000；/api 走 proxy 免 CORS
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
