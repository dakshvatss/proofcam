import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, beforeEach, vi } from 'vitest'
import { timing } from '../state/useInspection'

beforeEach(() => {
  localStorage.clear()
  window.history.replaceState(null, '', '/')
  timing.pollMs = 5
  timing.maxPolls = 50
  // jsdom has no object URLs.
  URL.createObjectURL = vi.fn(() => 'blob:mock-photo')
  URL.revokeObjectURL = vi.fn()
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})
