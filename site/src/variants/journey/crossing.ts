// The hero of /journey: Sam's Dentist appointment, carried by the ghost from Personal to Work. This
// module holds what the island needs without React: which parts of the plan cross over in each
// mode (CONTEXT.md, Busy-Only Projection and Details Projection), and the carry's timeline.
import type { CrossingMode } from "../../demo/crossing"

export type { CrossingMode }
export const MODES: readonly CrossingMode[] = ["busy", "details"]

/** The parts of a plan, in the order its card shows them. */
export type Part = "title" | "time" | "place" | "description" | "guests" | "link"
export const PARTS: readonly Part[] = ["title", "time", "place", "description", "guests", "link"]

/** Whether `part` reaches the destination calendar. The time always does; guests and links never. */
export function crosses(part: Part, mode: CrossingMode): boolean {
  if (part === "time") return true
  if (part === "guests" || part === "link") return false
  return mode === "details"
}

/** The parts that stay with Sam, in card order: what peels off the ghost's copy and flies back. */
export function staysBehind(mode: CrossingMode): Part[] {
  return PARTS.filter((part) => !crosses(part, mode))
}

/** Every word of the plan, as the page passes it to the island (all copy comes from en.ts). */
export interface PlanText {
  title: string
  place: string
  description: string
  guests: string
  link: string
}

/** When the Dentist happens: Monday, 15:00 to 16:30, as in the home page's Crossing. */
export const DENTIST_TIME = { day: 0, start: 15, end: 16.5 } as const

/** 15.5 as "15:30". Clock times are not copy. */
export function clock(hours: number): string {
  const whole = Math.floor(hours)
  return `${String(whole).padStart(2, "0")}:${String(Math.round((hours - whole) * 60)).padStart(2, "0")}`
}

/** The first and last hour the Work calendar shows: every plan fits between them. */
export const WORK_HOURS = { from: 13, to: 17 } as const

/**
 * The carry, in milliseconds from the start of a run. A run starts and ends on the landed state
 * (what the page shows without JavaScript), so the first run picks up where the page already is.
 */
export const RUN = {
  /** The ghost flies back from where it rests to the plan in Sam's calendar. */
  fetch: [0, 900],
  /** It draws its own copy of the plan out into the open. Sam's plan stays where it was. */
  take: [900, 1700],
  /** The parts that stay behind peel off the copy one by one and fly home, and it waves. */
  peel: [1700, 3300],
  /** It carries what crosses over to Work. */
  carry: [3400, 5200],
  /** It sets it down in its slot. */
  set: [5200, 5700],
  /** It steps back to admire its work and says something about it. */
  settle: [5700, 6200],
  /** The whole run, rest included. */
  total: 10_000,
} as const

/** How long each part takes to fly home, and the delay between one part and the next. */
export const PEEL_MS = 700
export const PEEL_STAGGER_MS = 200

export type Moment = "rest" | "fetch" | "take" | "peel" | "carry" | "set" | "settle"

/** Which part of the run `ms` falls in. Between peel and carry the ghost is still waving. */
export function momentAt(ms: number): Moment {
  if (ms < RUN.fetch[1]) return "fetch"
  if (ms < RUN.take[1]) return "take"
  if (ms < RUN.carry[0]) return "peel"
  if (ms < RUN.carry[1]) return "carry"
  if (ms < RUN.set[1]) return "set"
  if (ms < RUN.settle[1]) return "settle"
  return "rest"
}

/** 0 before `range`, 1 after it, and the share of it in between. */
export function progress(ms: number, [from, to]: readonly [number, number]): number {
  if (ms <= from) return 0
  if (ms >= to) return 1
  return (ms - from) / (to - from)
}

/** When the `index`th part to stay behind starts and ends its flight home. */
export function peelWindow(index: number): [number, number] {
  const start = RUN.peel[0] + index * PEEL_STAGGER_MS
  return [start, start + PEEL_MS]
}

export const easeInOut = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2)
export const easeOut = (t: number) => 1 - (1 - t) ** 4
