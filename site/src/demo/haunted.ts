export const HAUNTED_PERIOD_MS = 9000
/** The moment shown when nothing animates: every incoming event already Busy. */
export const HAUNTED_STILL_MS = 8000

export interface HauntedFrame {
  ghost: { xPct: number; yPct: number; visible: boolean }
  shown: boolean[]
  busy: boolean[]
  fading: boolean
}

/** The Haunted Week at `ms`. `incomingDays` is the day of each event that crosses over. */
export function hauntedFrame(ms: number, incomingDays: readonly number[]): HauntedFrame {
  const t = ((ms % HAUNTED_PERIOD_MS) + HAUNTED_PERIOD_MS) % HAUNTED_PERIOD_MS
  const progress = Math.min(1, Math.max(0, (t - 1700) / 5200))
  const xPct = progress * 112 - 6
  return {
    ghost: { xPct, yPct: 52 + 26 * Math.sin((xPct / 100) * Math.PI * 3), visible: t >= 1500 && t <= 7300 },
    shown: incomingDays.map((_, index) => t > 200 + index * 170),
    busy: incomingDays.map((day) => xPct > day * 20 + 10),
    fading: t > 8500,
  }
}
