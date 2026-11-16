import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The example rule sets live in ../examples: allow the dev server to read them, and
// proxy /v1 to the Python execution API (uvicorn on :8000) for the simulator.
export default defineConfig({
  plugins: [react()],
  server: {
    fs: { allow: ['..'] },
    proxy: { '/v1': 'http://localhost:8000' },
  },
})
