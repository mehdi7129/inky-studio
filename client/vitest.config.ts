import { defineConfig } from 'vitest/config'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))

export default defineConfig({
  resolve: {
    alias: {
      '@': resolve(here, 'src'),
      '@shared': resolve(here, '..', 'shared'),
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    // Vitest 4 spawns a fresh node worker per test file by default. Boot of the
    // jsdom env + our setup file is slow enough on a cold cache that the 60 s
    // worker timeout hits before tests even start. Reusing the same context
    // across files keeps things fast and our suite is small enough not to need
    // strict isolation.
    isolate: false,
  },
})
