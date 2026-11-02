import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const configuredApiUrl = env.VITE_API_URL || ''
  const apiUrl = configuredApiUrl.includes('__')
    ? 'http://127.0.0.1:8000'
    : configuredApiUrl || 'http://127.0.0.1:8000'
  const configuredPort = Number(env.VITE_PORT)
  const port = Number.isInteger(configuredPort) && configuredPort > 0 && configuredPort <= 65535
    ? configuredPort
    : 5173

  return {
    plugins: [react()],
    server: {
      port,
      proxy: {
        '/api': { target: apiUrl, changeOrigin: true },
      },
    },
  }
})
