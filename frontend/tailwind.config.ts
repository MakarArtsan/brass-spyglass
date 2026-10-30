import type { Config } from 'tailwindcss'
import plugin from 'tailwindcss/plugin'
import { fonts, palette, statusColors, motion, type Theme } from './src/brand'

/** '#C9A24A' → '201 162 74' — формат для rgb(var(--x) / <alpha-value>) */
const rgbTriplet = (hex: string) => {
  const n = parseInt(hex.slice(1), 16)
  return `${(n >> 16) & 255} ${(n >> 8) & 255} ${n & 255}`
}

const cssVars = (theme: Theme) => ({
  'color-scheme': theme,
  ...Object.fromEntries(
    Object.entries(palette[theme]).map(([k, v]) => [`--${k}`, rgbTriplet(v)]),
  ),
  ...Object.fromEntries(
    Object.entries(statusColors[theme]).map(([k, v]) => [`--status-${k}`, rgbTriplet(v)]),
  ),
})

const tokenColor = (name: string) => `rgb(var(--${name}) / <alpha-value>)`

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ...Object.fromEntries(Object.keys(palette.dark).map((k) => [k, tokenColor(k)])),
        status: Object.fromEntries(
          Object.keys(statusColors.dark).map((k) => [k, tokenColor(`status-${k}`)]),
        ),
      },
      fontFamily: {
        display: [fonts.display],
        sans: [fonts.sans],
        mono: [fonts.mono],
      },
      transitionDuration: { fast: `${motion.fast * 1000}ms`, base: `${motion.base * 1000}ms` },
      minHeight: { touch: '44px' },
      minWidth: { touch: '44px' },
      screens: { lg: '1024px' },
    },
  },
  plugins: [
    // Палитра из brand.ts превращается в CSS-переменные — одна правда для обеих тем.
    plugin(({ addBase }) => {
      addBase({
        ':root': cssVars('dark'),
        ':root[data-theme="light"]': cssVars('light'),
      })
    }),
  ],
} satisfies Config
