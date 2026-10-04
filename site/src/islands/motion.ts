export const REVEAL_REST = 55
export const SWEEP_PERIOD_MS = 10_000
const SWEEP_CENTER = 50
const SWEEP_SWING = 38

export function clampPercent(percent: number): number {
  return Math.min(98, Math.max(2, percent))
}

/** The hero slider's position while it sweeps by itself. */
export function sweepPercent(ms: number, periodMs = SWEEP_PERIOD_MS): number {
  return SWEEP_CENTER + SWEEP_SWING * Math.sin((2 * Math.PI * ms) / periodMs)
}

/** The sweep time at which the slider is at `percent`, so a resumed sweep does not jump. */
export function sweepTimeFor(percent: number, periodMs = SWEEP_PERIOD_MS): number {
  const ratio = Math.min(1, Math.max(-1, (percent - SWEEP_CENTER) / SWEEP_SWING))
  return (Math.asin(ratio) / (2 * Math.PI)) * periodMs
}

/** How far the ghost's eyes move toward the pointer, in mark units. */
export function eyeOffset(dx: number, dy: number): { x: number; y: number } {
  const distance = Math.hypot(dx, dy)
  if (distance === 0) return { x: 0, y: 0 }
  return { x: Number(((dx / distance) * 1.3).toFixed(2)), y: Number(((dy / distance) * 1.1).toFixed(2)) }
}

export interface LoopConditions {
  onScreen: boolean
  pageVisible: boolean
  reducedMotion: boolean
  held: boolean
}

export function shouldAnimate(conditions: LoopConditions): boolean {
  return conditions.onScreen && conditions.pageVisible && !conditions.reducedMotion && !conditions.held
}
