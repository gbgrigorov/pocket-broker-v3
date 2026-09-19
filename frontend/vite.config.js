import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// Vite serves the app on 5173 and proxies everything Django owns. The Origin
// rewrite is what stops Django's CSRF check rejecting writes in development.
export default defineConfig({
  plugins: [vue()],
  // Django serves the built bundle from /static/. This has to be the real base
  // rather than a rewrite of index.html, because vue-router's lazy chunks are
  // requested at runtime and never pass through the HTML at all.
  base: '/static/',
  server: {
    port: 5173,
    proxy: Object.fromEntries(
      ['/api', '/media', '/admin', '/static'].map((path) => [
        path,
        {
          target: 'http://127.0.0.1:8420',
          changeOrigin: true,
          headers: { Origin: 'http://127.0.0.1:8420' },
        },
      ])
    ),
  },
  build: { outDir: 'dist', emptyOutDir: true },
})
