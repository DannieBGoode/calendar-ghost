// The /journey week's opening pass: the ghost, as the divider between "What you see" and "What
// work sees", sweeps from the right edge to the left, and each of Sam's plans arrives on work's
// side as Busy as it passes. Then it settles where the comparison rests.
import type { Box } from "../../demo/layout"
import { REVEAL_REST } from "../../islands/motion"
import { easeInOut, easeOut } from "./crossing"

/** Where the pass starts and how far left it goes, as a share of the week's width. */
export const INTRO_FROM = 98
export const INTRO_TURN = 5
/** The sweep left, then the glide back to rest. Under five seconds in all. */
export const INTRO_SWEEP_MS = 2900
export const INTRO_MS = 4300

/** The divider's position `ms` into the pass. */
export function introSplit(ms: number): number {
  if (ms <= 0) return INTRO_FROM
  if (ms < INTRO_SWEEP_MS) return INTRO_FROM + (INTRO_TURN - INTRO_FROM) * easeInOut(ms / INTRO_SWEEP_MS)
  if (ms < INTRO_MS) return INTRO_TURN + (REVEAL_REST - INTRO_TURN) * easeOut((ms - INTRO_SWEEP_MS) / (INTRO_MS - INTRO_SWEEP_MS))
  return REVEAL_REST
}

/** Whether a plan laid out at `box` has reached work's side: the divider has passed its middle. */
export function hasArrived(box: Pick<Box, "leftPct" | "widthPct">, split: number): boolean {
  return split <= box.leftPct + box.widthPct / 2
}
