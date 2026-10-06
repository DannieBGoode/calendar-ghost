// The Haunted Week ("One week, every calendar."): Sam's Work week, where the plans from Personal
// and Family arrive in transit, the ghost passes over each one, and each becomes Busy; Work's own
// meetings stay. This module is the loop's clock and the ghost's path, in calendar units (days or
// columns, and hours since the week's first hour); HauntedWeek.tsx and demos.css turn them into
// places on screen, for the wide week (one row of five days) and the phone week (two rows: Monday
// to Wednesday, then Thursday and Friday).
import { DAY_START, DAYS, type DemoEvent } from "./week"

export const HAUNTED_PERIOD_MS = 9000
/** The moment shown when nothing animates: every incoming event already Busy, the ghost gone. */
export const HAUNTED_STILL_MS = 8000

/** When the first incoming event starts to arrive, and how far apart the next ones follow. */
const ARRIVE_MS = 250
const ARRIVE_STEP_MS = 180
/** The ghost's run: from off the week's left edge, over each incoming event, off its right edge. */
const RUN_START_MS = 1700
const RUN_MS = 5400
/** When everything fades away before the loop starts again. */
const FADE_MS = 8500

/** How high the ghost hops between two events, in hours, and the highest it goes: a little above
 * the week's first hour, so it stays inside the frame. */
const HOP_HOURS = 1.4
const TOP_HOURS = -0.35

/** The phone week shows this many days in a row (Monday to Wednesday, then Thursday and Friday). */
export const PHONE_COLUMNS = 3

/** A point on the ghost's path: `x` in days (wide) or columns (phone), `row` in phone rows, `y` in
 * hours since the week's first hour. */
export interface PathPoint {
  x: number
  row: number
  y: number
}

/** Where an event sits in the phone week: its column and its row. */
export function phoneCell(day: number): { col: number; row: number } {
  return { col: day % PHONE_COLUMNS, row: Math.floor(day / PHONE_COLUMNS) }
}

/**
 * The ghost's waypoints for one layout: in from beyond the left edge, then the middle of each
 * incoming event's top edge (where its hem brushes the event), then out beyond the right edge.
 */
export function waypoints(incoming: readonly DemoEvent[], layout: "wide" | "phone"): PathPoint[] {
  const touch = incoming.map((event) => {
    const cell = layout === "wide" ? { col: event.day, row: 0 } : phoneCell(event.day)
    return { x: cell.col + 0.5, row: cell.row, y: event.start - DAY_START }
  })
  const first = touch[0] ?? { x: 0.5, row: 0, y: 3 }
  const last = touch[touch.length - 1] ?? { x: DAYS - 0.5, row: 0, y: 3 }
  const right = layout === "wide" ? DAYS : PHONE_COLUMNS
  return [
    { x: -0.9, row: first.row, y: Math.max(1, first.y - 2) },
    ...touch,
    { x: right + 0.9, row: last.row, y: Math.max(1, last.y - 1.5) },
  ]
}

/**
 * How the path leaves a waypoint. Across, it heads from the waypoint before to the one after
 * (as a Catmull-Rom curve does), but only along its own row of the phone week: where a neighbour
 * sits on another row, it keeps its row's direction, so the ghost reaches the end of a row and
 * swings down to the next one rather than doubling back over an event. Up and down it is level,
 * so the ghost glides along each event's top edge as it touches it.
 */
function tangent(points: readonly PathPoint[], index: number): PathPoint {
  const here = points[index]!
  const before = points[index - 1]
  const after = points[index + 1]
  const sameRow = (other: PathPoint | undefined) => other !== undefined && other.row === here.row
  let x = 0
  if (sameRow(before) && sameRow(after)) x = (after!.x - before!.x) / 2
  else if (sameRow(after)) x = after!.x - here.x
  else if (sameRow(before)) x = here.x - before!.x
  else if (before && after) x = (after.x - before.x) / 2
  return { x, row: 0, y: 0 }
}

/** A smooth curve through every waypoint (cubic Hermite, with the tangents above), one segment
 * per stretch of time: `u` runs from 0 (the first waypoint) to 1 (the last). */
export function pointOnPath(points: readonly PathPoint[], u: number): PathPoint {
  const segments = points.length - 1
  const at = Math.min(segments, Math.max(0, u * segments))
  const index = Math.min(segments - 1, Math.floor(at))
  const t = at - index
  const [from, to] = [points[index]!, points[index + 1]!]
  const [leave, arrive] = [tangent(points, index), tangent(points, index + 1)]
  const t2 = t * t
  const t3 = t2 * t
  const [h00, h10, h01, h11] = [2 * t3 - 3 * t2 + 1, t3 - 2 * t2 + t, 3 * t2 - 2 * t3, t3 - t2]
  const blend = (key: keyof PathPoint) => h00 * from[key] + h10 * leave[key] + h01 * to[key] + h11 * arrive[key]
  // Between two touches the ghost hops up and over, so it comes down onto each event from above
  // rather than drifting through it, and it never rises past the top of the week.
  const hop = HOP_HOURS * Math.sin(Math.PI * t) ** 2
  return { x: blend("x"), row: blend("row"), y: Math.max(TOP_HOURS, blend("y") - hop) }
}

export type IncomingState = "away" | "transit" | "busy"

export interface HauntedFrame {
  /** How far the ghost is along its run, from 0 to 1, or null while it is out of sight. */
  run: number | null
  /** Each incoming event, in the order the ghost meets it. */
  incoming: IncomingState[]
  /** Everything fades away before the loop starts again. */
  fading: boolean
}

/** The Haunted Week at `ms`, for `count` incoming events that the ghost meets in order. */
export function hauntedFrame(ms: number, count: number): HauntedFrame {
  const t = ((ms % HAUNTED_PERIOD_MS) + HAUNTED_PERIOD_MS) % HAUNTED_PERIOD_MS
  const progress = (t - RUN_START_MS) / RUN_MS
  const running = progress >= 0 && progress <= 1
  // Waypoint 0 is the way in; event i is waypoint i + 1 of count + 2.
  const reached = Math.max(0, Math.min(1, progress)) * (count + 1)
  const incoming = Array.from({ length: count }, (_, index): IncomingState => {
    if (reached >= index + 1) return "busy"
    return t >= ARRIVE_MS + index * ARRIVE_STEP_MS ? "transit" : "away"
  })
  return { run: running ? progress : null, incoming, fading: t >= FADE_MS }
}
