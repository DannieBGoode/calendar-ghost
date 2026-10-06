// Hero E3's diagram, read left to right. On the left, "Your calendars": Sam's three calendars as
// hero E2's pills (portrait, name, and one event line), Work among them. In the middle, the ghost
// character. On the right, a day: Sam's Work calendar as work sees it, or (the switch over it)
// Sam's own Personal calendar. Events travel, calendars do not: a chip carrying an event's title
// leaves each pill and goes through the ghost. Bound for Work, the Dentist and the family dinner
// lose their titles there (Busy-Only Projection) and leave as indigo "Busy" chips; the dropped
// titles stay by the ghost, struck through. Work's own Standup passes with its title. Bound for
// Personal, nothing is held back. Each lands in the day at its event's time.
//
// Everything here is plain data and geometry, worked out at build time, so the page draws the
// diagram, and starts its motion, without JavaScript. Two layouts share it: `wide` (pills on the
// left, Work on the right) and `tall` for phones (pills on top, the ghost, then Work).

import type { Calendar } from "../../avatars"
import { DAY_END, DAY_START, SAM_WEEK } from "../../demo/week"
import { arcLength, cubicPath, link, turnDown, type Box, type Cubic, type Point } from "./node-diagram"

export type CalendarKey = Calendar
export type EventKey = "standup" | "dentist" | "familyDinner"

export interface HubEvent {
  key: EventKey
  /** Hours, so 15.5 is 15:30. */
  start: number
  end: number
}

/** One of Sam's calendars, shown with Sam's portrait for its account, and its one event that day. */
export interface Source {
  key: CalendarKey
  event: HubEvent
}

function monday(key: "dentist" | "standup"): HubEvent {
  const event = SAM_WEEK.find((item) => item.key === key && item.day === 0)
  if (!event) throw new Error(`Sam's Monday has no ${key}`)
  return { key, start: event.start, end: event.end }
}

/** Sam's calendars, in the order of their events. The Standup and the Dentist are Monday's, read
 * from Sam's week (as in the Week section); the family dinner falls after the hours the week
 * shows, so it never contradicts it. */
export const SOURCES: readonly Source[] = [
  { key: "work", event: monday("standup") },
  { key: "personal", event: monday("dentist") },
  { key: "family", event: { key: "familyDinner", start: 18.5, end: 19.5 } },
]

/** How an event shows on Work: Work's own keeps its title; Personal's and Family's arrive as Busy
 * (the Rules mockup's rules: Personal and Family to Work, Busy only). */
export function showsOnWork(source: Source): "own" | "busy" {
  return source.key === "work" ? "own" : "busy"
}

/** Whether an event falls inside the hours the week (demo/week.ts) shows. */
export function inWeekHours(event: HubEvent): boolean {
  return event.end > DAY_START && event.start < DAY_END
}

/** A clock time, as "07:30". */
export function clock(hours: number): string {
  const whole = Math.floor(hours)
  const minutes = Math.round((hours - whole) * 60)
  return `${String(whole).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`
}

/** The hours Work's day shows. */
export const HOURS = { start: 9, end: 20 } as const

// Motion ----------------------------------------------------------------------------------------

/** How fast a chip travels, in diagram units per second. */
export const SPEED = 150
/** How long a chip spends inside the ghost before it leaves. */
export const THROUGH_S = 0.55
/** When each event's chip passes through the ghost, in seconds from the first paint: the Dentist
 * first, the point of the whole diagram. */
export const PASSES: Record<CalendarKey, number> = { personal: 1.2, work: 2.5, family: 3.8 }
/** How long a landed block, or a dropped title, takes to appear. */
export const LAND_S = 0.5

// Layouts ----------------------------------------------------------------------------------------

export type LayoutKind = "wide" | "tall"

export interface Pill extends Box, Source {}

/** A block in Work's day: Work's own meeting, or a copy shown as Busy. */
export interface Block extends Box {
  source: CalendarKey
  event: HubEvent
  shows: "own" | "busy"
  /** When it appears, in seconds from the first paint. */
  lands: number
}

/** One chip's run along one hairline. */
export interface Leg {
  source: CalendarKey
  /** Into the ghost (with its title, in its calendar's colour) or out of it (as it shows on Work). */
  side: "in" | "out"
  shows: "own" | "busy"
  /** Whether the chip's title drops away as it reaches the ghost (an event bound for Busy). */
  drops: boolean
  d: string
  length: number
  /** When it sets off, in seconds from the first paint (negative: already on its way). */
  delay: number
  duration: number
}

/** A title the ghost kept back, resting by it, struck through. */
export interface Trace extends Point {
  source: CalendarKey
  event: EventKey
  /** When it appears: as its chip's title drops at the ghost. */
  appears: number
}

export interface Hub {
  kind: LayoutKind
  width: number
  height: number
  /** Where the two quiet labels sit (their left end and middle): over the calendars, over Work. */
  labels: { calendars: Point; work: Point }
  pills: Pill[]
  /** Work's outlined day: its box, the height of its header, and where its hours start. */
  work: Box & { header: number; dayTop: number; hour: number; gutter: number }
  /** Where each hour starts in Work's day, with its clock time, for the hour lines and labels. */
  hours: { y: number; hour: number }[]
  blocks: Block[]
  curves: { id: string; d: string }[]
  legs: Leg[]
  traces: Trace[]
  /** Where the dropped titles sit by the ghost: under it (wide) or to its left (tall). */
  traceAnchor: "middle" | "end"
  /** The ghost's box (the character's whole 64-unit drawing). */
  ghost: Box
  /** When each chip passes through the ghost, in seconds from the first paint, in order. */
  passes: number[]
  /** How long the whole run lasts. */
  duration: number
}

/** Points on the character's body, which spans x 12 to 52 and y 8 to 54 of its 64-unit drawing. */
function ghostEdges(box: Box) {
  const unit = box.width / 64
  const cx = box.x + box.width / 2
  return {
    left: { x: box.x + 13 * unit, y: box.y + 33 * unit },
    right: { x: box.x + 51 * unit, y: box.y + 33 * unit },
    top: { x: cx, y: box.y + 9 * unit },
    bottom: { x: cx, y: box.y + 53 * unit },
  }
}

interface Frame {
  width: number
  height: number
  labels: Hub["labels"]
  pills: Pill[]
  ghost: Box
  work: Hub["work"]
  inset: number
  into: (pill: Pill) => Cubic
  /** A chip's hairline from the ghost to its block; the tall layout has one for all of them. */
  out: (block: Box) => Cubic
  shared: boolean
  trace: (index: number) => Point
  traceAnchor: Hub["traceAnchor"]
}

/** Work's day: header, then the hours at one even height each, with a gutter for their labels. */
function workDay(box: Box, header: number, hour: number, gutter: number): Hub["work"] {
  return { ...box, header, dayTop: box.y + header + 6, hour, gutter }
}
const dayHeight = (header: number, hour: number) => header + 6 + (HOURS.end - HOURS.start) * hour + 6

function wideFrame(): Frame {
  const width = 1040
  const top = 46
  const header = 50
  const hour = 24
  const workHeight = dayHeight(header, hour)
  const work = workDay({ x: width - 284 - 0.5, y: top, width: 284, height: workHeight }, header, hour, 52)
  const middle = top + workHeight / 2
  // The pills sit close together, as hero E2's do, centred on the ghost's line: Personal on it.
  const pill = { width: 214, height: 54, pitch: 70 }
  const stack = SOURCES.length * pill.pitch - (pill.pitch - pill.height)
  const pills = SOURCES.map((source, index) => ({ ...source, x: 0.5, y: middle - stack / 2 + index * pill.pitch, width: pill.width, height: pill.height }))
  const size = 92
  const center = (pill.width + work.x) / 2
  const edges = ghostEdges({ x: 0, y: 0, width: size, height: size })
  const ghost = { x: center - size / 2, y: middle - edges.left.y, width: size, height: size }
  const placed = ghostEdges(ghost)
  const hubIn = { x: placed.left.x - 6, y: middle }
  const hubOut = { x: placed.right.x + 6, y: middle }
  return {
    width,
    height: Math.ceil(top + workHeight + 1),
    labels: { calendars: { x: 0.5, y: middle - stack / 2 - 22 }, work: { x: work.x, y: top - 22 } },
    pills,
    ghost,
    work,
    inset: 10,
    into: (item) => link({ x: item.x + item.width, y: item.y + item.height / 2 }, hubIn, "x"),
    out: (block) => link(hubOut, { x: work.x, y: block.y + block.height / 2 }, "x"),
    shared: false,
    trace: (index) => ({ x: center, y: placed.bottom.y + 16 + index * 17 }),
    traceAnchor: "middle",
  }
}

/** Where each calendar sits on a phone: two columns, the right one half a row lower, so their
 * hairlines into the ghost never meet. */
const TALL_PLACES: Record<CalendarKey, { column: 0 | 1; row: number }> = {
  work: { column: 0, row: 0 },
  personal: { column: 1, row: 0.5 },
  family: { column: 0, row: 1 },
}

function tallFrame(): Frame {
  const width = 300
  const center = width / 2
  const pill = { width: 138, height: 40, pitch: 48 }
  const top = 22
  const pills = SOURCES.map((source) => {
    const place = TALL_PLACES[source.key]
    return { ...source, x: place.column === 0 ? 0.5 : width - pill.width - 0.5, y: top + place.row * pill.pitch, width: pill.width, height: pill.height }
  })
  const bottom = Math.max(...pills.map((item) => item.y + item.height))
  const size = 64
  const ghost = { x: center - size / 2, y: bottom + 30, width: size, height: size }
  const edges = ghostEdges(ghost)
  const hubIn = { x: center, y: edges.top.y - 3 }
  const hubOut = { x: center, y: edges.bottom.y + 4 }
  const header = 42
  const hour = 24
  const labelRow = 52
  const workTop = ghost.y + ghost.height + labelRow
  const work = workDay({ x: 0.5, y: workTop, width: width - 1, height: dayHeight(header, hour) }, header, hour, 40)
  return {
    width,
    height: Math.ceil(workTop + work.height + 1),
    labels: { calendars: { x: 0.5, y: 9 }, work: { x: work.x, y: workTop - labelRow / 2 } },
    pills,
    ghost,
    work,
    inset: 7,
    into: (item) => turnDown({ x: item.x < center ? item.x + item.width : item.x, y: item.y + item.height / 2 }, hubIn),
    out: () => link(hubOut, { x: center, y: workTop }, "y"),
    shared: true,
    trace: (index) => ({ x: ghost.x - 4, y: edges.left.y - 8 + index * 15 }),
    traceAnchor: "end",
  }
}

const r2 = (value: number) => Math.round(value * 100) / 100

/** Builds one layout of the diagram: the pills, Work's day, the hairlines, and the chips. */
export function buildHub(kind: LayoutKind): Hub {
  const frame = kind === "wide" ? wideFrame() : tallFrame()
  const { work } = frame
  const place = (event: HubEvent): Box => ({
    x: work.x + work.gutter,
    y: work.dayTop + (event.start - HOURS.start) * work.hour + 1,
    width: work.width - work.gutter - frame.inset,
    height: (event.end - event.start) * work.hour - 2,
  })

  const curves: Hub["curves"] = []
  const legs: Leg[] = []
  const blocks: Block[] = []
  const traces: Trace[] = []
  if (frame.shared) curves.push({ id: "to-work", d: cubicPath(frame.out(place(SOURCES[0]!.event))) })

  for (const pill of frame.pills) {
    const shows = showsOnWork(pill)
    const slot = place(pill.event)
    const pass = PASSES[pill.key]
    const into = frame.into(pill)
    const inLength = arcLength(into)
    curves.push({ id: `from-${pill.key}`, d: cubicPath(into) })
    legs.push({ source: pill.key, side: "in", shows: "own", drops: shows === "busy", d: cubicPath(into), length: inLength, delay: r2(pass - inLength / SPEED), duration: r2(inLength / SPEED) })
    const out = frame.out(slot)
    const outLength = arcLength(out)
    const leaves = pass + THROUGH_S
    if (!frame.shared) curves.push({ id: `to-${pill.key}`, d: cubicPath(out) })
    legs.push({ source: pill.key, side: "out", shows, drops: false, d: cubicPath(out), length: outLength, delay: r2(leaves), duration: r2(outLength / SPEED) })
    blocks.push({ ...slot, source: pill.key, event: pill.event, shows, lands: r2(leaves + outLength / SPEED) })
    if (shows === "busy") traces.push({ ...frame.trace(traces.length), source: pill.key, event: pill.event.key, appears: r2(pass) })
  }

  const hours: Hub["hours"] = []
  for (let hour = HOURS.start; hour < HOURS.end; hour += 1) hours.push({ y: work.dayTop + (hour - HOURS.start) * work.hour, hour })

  return {
    kind,
    width: frame.width,
    height: frame.height,
    labels: frame.labels,
    pills: frame.pills,
    work,
    hours,
    blocks,
    curves,
    legs,
    traces,
    traceAnchor: frame.traceAnchor,
    ghost: frame.ghost,
    passes: Object.values(PASSES).sort((a, b) => a - b),
    duration: r2(Math.max(...blocks.map((block) => block.lands)) + LAND_S),
  }
}

/** The ghost's face over the run: neutral, pleased for a moment as each chip passes through it,
 * and pleased at rest. Returns keyframe stops (percent of the run, and the pleased face's opacity). */
export function faceStops(hub: Hub): [number, number][] {
  const at = (seconds: number) => Math.round((Math.max(0, seconds) / hub.duration) * 1000) / 10
  const stops: [number, number][] = [[0, 0]]
  hub.passes.forEach((pass, index) => {
    stops.push([at(pass - 0.1), 0], [at(pass - 0.06), 1])
    if (index < hub.passes.length - 1) stops.push([at(pass + 0.85), 1], [at(pass + 0.89), 0])
  })
  stops.push([100, 1])
  return stops
}
