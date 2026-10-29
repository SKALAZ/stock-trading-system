import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 개발 서버(npm run dev)에서는 /api 요청을 모니터링 API로 넘긴다
export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: { '/api': process.env.API_URL || 'http://localhost:8000' },
  },
})
