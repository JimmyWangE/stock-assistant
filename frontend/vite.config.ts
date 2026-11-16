import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [vue()],
  server: {
    // 本地开发时把 /api 转给本机后端；线上由 nginx 转发
    proxy: { '/api': 'http://localhost:8000' },
  },
})
