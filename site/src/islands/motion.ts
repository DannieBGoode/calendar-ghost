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
