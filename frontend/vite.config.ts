import path from 'node:path'
import react from '@vitejs/plugin-react'
import { defineConfig, type Plugin } from 'vite'

/** Шрифты нужны для первой отрисовки: предзагрузка убирает подмену шрифта («скачок») при показе. */
function preloadCriticalFonts(): Plugin {
  const wanted = [/manrope-cyrillic-wght-normal.*\.woff2$/, /manrope-latin-wght-normal.*\.woff2$/, /cormorant-garamond-cyrillic-600-normal.*\.woff2$/]
  return {
    name: 'preload-critical-fonts',
    transformIndexHtml: {
      order: 'post',
      handler(html, ctx) {
        const files = Object.keys(ctx.bundle ?? {}).filter((f) => wanted.some((re) => re.test(f)))
        return {
          html,
          tags: files.map((f) => ({
            tag: 'link',
            attrs: { rel: 'preload', as: 'font', type: 'font/woff2', crossorigin: '', href: `/${f}` },
            injectTo: 'head' as const,
          })),
        }
      },
    },
  }
}

export default defineConfig({
  plugins: [react(), preloadCriticalFonts()],
  resolve: { alias: { '@': path.resolve(__dirname, 'src') } },
  server: { port: 5173, proxy: { '/api': 'http://localhost:8000' } },
  build: {
    outDir: 'dist',
    sourcemap: false,
    rollupOptions: {
      output: {
        // Библиотеки меняются редко — отдельные чанки кэшируются между релизами. framer-motion сюда не входит:
        // его лёгкое ядро идёт с приложением, а анимации и жесты грузятся своим чанком (lib/motionFeatures).
        manualChunks: {
          react: ['react', 'react-dom', 'react-router-dom'],
          query: ['@tanstack/react-query'],
        },
      },
    },
  },
})
