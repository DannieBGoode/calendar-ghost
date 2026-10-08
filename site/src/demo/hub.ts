// The home hero's diagram (sections/Hero.astro): Sam's calendars on the left, the ghost at the hub,
// and a short day on the right: Sam's Work calendar as work sees it, or (the switch over the whole
// diagram) Sam's Personal calendar. A chip carrying an event's title leaves each calendar and goes
// through the ghost. Bound for Work, the gym session and the family dinner lose their titles there
// (Busy-Only Projection), which the ghost keeps back, and leave as indigo "Busy" chips; Work's own
// client call passes with its title. Bound for Personal, nothing is held back. Each lands in the
// day at its time, the day rests, and the cycle starts again.
//
// The day is Sam's Tuesday, so it can stay short: the gym session and the client call are
// Tuesday's in Sam's week (demo/week.ts, as in the Week section), and the family dinner falls after
// the hours the week shows.
//
// Everything here is plain data and geometry, worked out at build time, so the page draws the
// diagram, and starts its motion, without JavaScript. Two layouts share it: `wide` (the calendars
// on the left, each name and event set flush against its portrait, whose ring its hairline leaves
// from; the day on the right) and `tall` for phones (a row of calendars on top, each portrait over
// its name and event; the ghost and what it keeps back; then the day).

import type { Calendar } from "../avatars"
import { SAM_WEEK } from "./week"

export type CalendarKey = Calendar
export type EventKey = "gym" | "clientCall" | "familyDinner"

interface HubEvent {
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

function tuesday(key: "gym" | "clientCall"): HubEvent {
  const event = SAM_WEEK.find((item) => item.key === key && item.day === 1)
  if (!event) throw new Error(`Sam's Tuesday has no ${key}`)
  return { key, start: event.start, end: event.end }
}

/** Sam's calendars, in the order of their events. */
export const SOURCES: readonly Source[] = [
  { key: "personal", event: tuesday("gym") },
  { key: "work", event: tuesday("clientCall") },
  { key: "family", event: { key: "familyDinner", start: 18, end: 19 } },
]

/** How an event shows on Work: Work's own keeps its title; Personal's and Family's arrive as Busy
 * (the Rules mockup's rules: Personal and Family to Work, Busy only). */
export function showsOnWork(source: Source): "own" | "busy" {
  return source.key === "work" ? "own" : "busy"
}

/** A clock time, as "07:30". */
export function clock(hours: number): string {
  const whole = Math.floor(hours)
  const minutes = Math.round((hours - whole) * 60)
  return `${String(whole).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`
}

/** The hours the day shows: just around the day's events. */
export const HOURS = { start: 11.5, end: 19.5 } as const

// Motion ----------------------------------------------------------------------------------------

/** How fast a chip travels, in diagram units per second. */
export const SPEED = 150
/** How long a chip spends inside the ghost before it leaves. */
export const THROUGH_S = 0.55
/** When each event's chip passes through the ghost, in seconds from the start of a cycle: the
 * gym session first, then Work's own call, then the family dinner. */
export const PASSES: Record<CalendarKey, number> = { personal: 2, work: 3.3, family: 4.6 }
/** How long a landed block, or a held-back title, takes to appear, and to go at a cycle's end. */
export const LAND_S = 0.5
/** How long the day rests, everything landed, before the cycle starts again. */
export const REST_S = 3.5

// Geometry --------------------------------------------------------------------------------------

export interface Point {
  x: number
  y: number
}

export interface Box extends Point {
  width: number
  height: number
}

/** A cubic Bézier curve. */
export interface Cubic {
  p0: Point
  p1: Point
  p2: Point
  p3: Point
}

const r2 = (value: number) => Math.round(value * 100) / 100

/** The curve as SVG path data. */
export function cubicPath({ p0, p1, p2, p3 }: Cubic): string {
  return `M${r2(p0.x)} ${r2(p0.y)}C${r2(p1.x)} ${r2(p1.y)} ${r2(p2.x)} ${r2(p2.y)} ${r2(p3.x)} ${r2(p3.y)}`
}

export function pointAt({ p0, p1, p2, p3 }: Cubic, t: number): Point {
  const u = 1 - t
  const a = u * u * u
  const b = 3 * u * u * t
  const c = 3 * u * t * t
  const d = t * t * t
  return { x: a * p0.x + b * p1.x + c * p2.x + d * p3.x, y: a * p0.y + b * p1.y + c * p2.y + d * p3.y }
}

/** The curve's length, measured along many short chords. */
export function arcLength(curve: Cubic): number {
  const steps = 200
  let length = 0
  let previous = curve.p0
  for (let step = 1; step <= steps; step += 1) {
    const point = pointAt(curve, step / steps)
    length += Math.hypot(point.x - previous.x, point.y - previous.y)
    previous = point
  }
  return length
}

/** A curve that leaves `from` and arrives at `to` both along the x axis (wide) or the y axis. */
function link(from: Point, to: Point, axis: "x" | "y"): Cubic {
  if (axis === "x") {
    const reach = (to.x - from.x) / 2
    return { p0: from, p1: { x: from.x + reach, y: from.y }, p2: { x: to.x - reach, y: to.y }, p3: to }
  }
  const reach = (to.y - from.y) / 2
  return { p0: from, p1: { x: from.x, y: from.y + reach }, p2: { x: to.x, y: to.y - reach }, p3: to }
}

// Layouts ----------------------------------------------------------------------------------------

export type LayoutKind = "wide" | "tall"

/** One of Sam's calendars as drawn: its box (its portrait and its text), and its portrait's middle. */
interface Pill extends Box, Source {
  portrait: Point
}

/** A block in the day: Work's own meeting, or a copy shown as Busy. */
interface Block extends Box {
  source: CalendarKey
  event: HubEvent
  shows: "own" | "busy"
  /** When it appears, in seconds from the start of a cycle. */
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
  /** The hairline it runs, by id (see `curves`). */
  curve: string
  d: string
  length: number
  /** When it sets off, in seconds from the start of a cycle. */
  delay: number
  duration: number
}

/** A title the ghost keeps back from Work, shown by it as a small chip under a caption. */
interface Kept extends Point {
  source: CalendarKey
  event: EventKey
  /** When it appears: as its chip's title drops at the ghost. */
  appears: number
}

export interface Hub {
  kind: LayoutKind
  width: number
  height: number
  /** Where the two column labels sit, over the calendars and over the day, and which way each
   * runs from that point. On wide screens both hold to the edge facing the ghost: the calendars'
   * label ends where the rings do, and the day's starts at its panel's edge. */
  labels: { calendars: Point & { anchor: "start" | "end" }; day: Point }
  pills: Pill[]
  /** Each portrait's width. */
  portrait: number
  /** The day: its box, the height of its header, where its hours start, and its label gutter. */
  day: Box & { header: number; dayTop: number; hour: number; gutter: number }
  /** Each whole hour in the day, for its line and its label. */
  hours: { y: number; hour: number }[]
  blocks: Block[]
  curves: { id: string; d: string }[]
  legs: Leg[]
  /** The caption over the kept titles, and the titles themselves (their middle). */
  kept: { caption: Point; titles: Kept[] }
  /** The ghost's box (the character's whole 64-unit drawing). */
  ghost: Box
  /** When each chip passes through the ghost, in seconds from the start of a cycle, in order. */
  passes: number[]
  /** How long one cycle lasts: the run, then the rest. */
  cycle: number
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
  portrait: number
  ghost: Box
  day: Hub["day"]
  inset: number
  into: (pill: Pill) => Cubic
  /** A chip's hairline from the ghost to its block; the tall layout has one for all of them. */
  out: (block: Box) => Cubic
  shared: boolean
  kept: { caption: Point; title: (index: number) => Point }
}

function dayBox(box: { x: number; y: number; width: number }, header: number, hour: number, gutter: number): Hub["day"] {
  const height = header + 6 + (HOURS.end - HOURS.start) * hour + 6
  return { ...box, height, header, dayTop: box.y + header + 6, hour, gutter }
}

/** The space between a portrait and its ring, and from the ring to where a hairline starts. */
export const RING_GAP = 3.5
const RING_CLEAR = 7

/** The wide layout's calendars: each box holds the name and event (set flush right against the
 * portrait) and the portrait, whose ring ends at the box's right edge. Their stack spans the day's
 * height, so both columns start and end level and their labels sit as far above them. */
const WIDE = { portrait: 52, width: 228, height: 66 } as const

/** The wide layout, left to right: the calendars in a stack as tall as the day, the ghost on the
 * figure's centre line (the axis of the view switch over it), and the day. */
function wideFrame(): Frame {
  const width = 1040
  const header = 46
  const hour = 26
  const dayHeight = header + 12 + (HOURS.end - HOURS.start) * hour
  const labelRow = 30
  const middle = labelRow + dayHeight / 2
  const day = dayBox({ x: width - 284 - 0.5, y: middle - dayHeight / 2, width: 284 }, header, hour, 52)
  const pitch = (dayHeight - WIDE.height) / (SOURCES.length - 1)
  // The ring's outer edge: its radius, the gap, and half its 3-unit stroke.
  const ringEdge = WIDE.portrait / 2 + RING_GAP + 1.5
  const pills = SOURCES.map((source, index) => {
    const box = { x: 0.5, y: middle - dayHeight / 2 + index * pitch, width: WIDE.width, height: WIDE.height }
    return { ...source, ...box, portrait: { x: box.x + box.width - ringEdge, y: box.y + box.height / 2 } }
  })
  const size = 92
  const center = width / 2
  const edges = ghostEdges({ x: 0, y: 0, width: size, height: size })
  const ghost = { x: center - size / 2, y: middle - edges.left.y, width: size, height: size }
  const placed = ghostEdges(ghost)
  const hubIn = { x: placed.left.x - 6, y: middle }
  const hubOut = { x: placed.right.x + 6, y: middle }
  const labelY = day.y - 16
  return {
    width,
    height: Math.ceil(day.y + day.height + 1),
    labels: { calendars: { x: 0.5 + WIDE.width, y: labelY, anchor: "end" }, day: { x: day.x, y: labelY } },
    pills,
    portrait: WIDE.portrait,
    ghost,
    day,
    inset: 10,
    into: (item) => link({ x: item.portrait.x + WIDE.portrait / 2 + RING_GAP + RING_CLEAR, y: item.portrait.y }, hubIn, "x"),
    out: (block) => link(hubOut, { x: day.x, y: block.y + block.height / 2 }, "x"),
    shared: false,
    kept: { caption: { x: center, y: placed.bottom.y + 16 }, title: (index) => ({ x: center, y: placed.bottom.y + 38 + index * 24 }) },
  }
}

/**
 * The phone layout, one tidy column down the screen: Sam's three calendars in a row (a portrait in
 * its ring over the name over the event), each hairline dropping straight down into the ghost's head;
 * under the ghost, centred, the titles it keeps back from Work; then the day. Chips leave the
 * ghost by its right side and go down a lane of their own, beside the kept titles, into the day,
 * so nothing they carry crosses anything else.
 */
const TALL = { width: 300, pillGap: 8, pillHeight: 76, ghost: 64, keptPitch: 24, lane: 254, portrait: 34, portraitTop: 6 } as const

function tallFrame(): Frame {
  const { width } = TALL
  const center = width / 2
  const pillWidth = (width - 1 - 2 * TALL.pillGap) / 3
  const top = 22
  const pills = SOURCES.map((source, index) => {
    const x = 0.5 + index * (pillWidth + TALL.pillGap)
    return { ...source, x, y: top, width: pillWidth, height: TALL.pillHeight, portrait: { x: x + pillWidth / 2, y: top + TALL.portraitTop + TALL.portrait / 2 } }
  })
  const size = TALL.ghost
  const ghost = { x: center - size / 2, y: top + TALL.pillHeight + 40, width: size, height: size }
  const edges = ghostEdges(ghost)
  const hubIn = { x: center, y: edges.top.y - 3 }
  const hubOut = { x: edges.right.x + 2, y: edges.left.y + 6 }
  const caption = { x: center, y: edges.bottom.y + 18 }
  const title = (index: number) => ({ x: center, y: caption.y + 22 + index * TALL.keptPitch })
  const keptBottom = title(1).y + 12
  const labelRow = 30
  const day = dayBox({ x: 0.5, y: keptBottom + labelRow, width: width - 1 }, 42, 24, 40)
  return {
    width,
    height: Math.ceil(day.y + day.height + 1),
    labels: { calendars: { x: 0.5, y: 9, anchor: "start" }, day: { x: 0.5, y: day.y - 13 } },
    pills,
    portrait: TALL.portrait,
    ghost,
    day,
    inset: 7,
    into: (item) => link({ x: item.portrait.x, y: item.y + item.height }, hubIn, "y"),
    // Out to the right at once, then straight down the lane, so a chip is clear of the kept
    // titles before it reaches their row.
    out: () => ({ p0: hubOut, p1: { x: TALL.lane, y: hubOut.y }, p2: { x: TALL.lane, y: hubOut.y + 24 }, p3: { x: TALL.lane, y: day.y } }),
    shared: true,
    kept: { caption, title },
  }
}

/** Builds one layout of the diagram: the pills, the day, the hairlines, and the chips. */
export function buildHub(kind: LayoutKind): Hub {
  const frame = kind === "wide" ? wideFrame() : tallFrame()
  const { day } = frame
  const place = (event: HubEvent): Box => ({
    x: day.x + day.gutter,
    y: day.dayTop + (event.start - HOURS.start) * day.hour + 1,
    width: day.width - day.gutter - frame.inset,
    height: (event.end - event.start) * day.hour - 2,
  })

  const curves: Hub["curves"] = []
  const legs: Leg[] = []
  const blocks: Block[] = []
  const titles: Kept[] = []
  if (frame.shared) curves.push({ id: "to-day", d: cubicPath(frame.out(place(SOURCES[0]!.event))) })

  for (const pill of frame.pills) {
    const shows = showsOnWork(pill)
    const slot = place(pill.event)
    const pass = PASSES[pill.key]
    const into = frame.into(pill)
    const inLength = arcLength(into)
    curves.push({ id: `from-${pill.key}`, d: cubicPath(into) })
    legs.push({ source: pill.key, side: "in", shows: "own", drops: shows === "busy", curve: `from-${pill.key}`, d: cubicPath(into), length: inLength, delay: r2(pass - inLength / SPEED), duration: r2(inLength / SPEED) })
    const out = frame.out(slot)
    const outLength = arcLength(out)
    const leaves = pass + THROUGH_S
    const outCurve = frame.shared ? "to-day" : `to-${pill.key}`
    if (!frame.shared) curves.push({ id: outCurve, d: cubicPath(out) })
    legs.push({ source: pill.key, side: "out", shows, drops: false, curve: outCurve, d: cubicPath(out), length: outLength, delay: r2(leaves), duration: r2(outLength / SPEED) })
    blocks.push({ ...slot, source: pill.key, event: pill.event, shows, lands: r2(leaves + outLength / SPEED) })
    if (shows === "busy") titles.push({ ...frame.kept.title(titles.length), source: pill.key, event: pill.event.key, appears: r2(pass) })
  }

  const hours: Hub["hours"] = []
  for (let hour = Math.ceil(HOURS.start); hour < HOURS.end; hour += 1) hours.push({ y: day.dayTop + (hour - HOURS.start) * day.hour, hour })

  return {
    kind,
    width: frame.width,
    height: frame.height,
    labels: frame.labels,
    pills: frame.pills,
    portrait: frame.portrait,
    day,
    hours,
    blocks,
    curves,
    legs,
    kept: { caption: frame.kept.caption, titles },
    ghost: frame.ghost,
    passes: Object.values(PASSES).sort((a, b) => a - b),
    cycle: r2(Math.max(...blocks.map((block) => block.lands)) + LAND_S + REST_S),
  }
}

// One cycle, as keyframe stops -------------------------------------------------------------------

/** A keyframe stop: percent of the cycle, and the values at it. */
export type Stop = [number, Record<string, string | number>]

/** Percent of the cycle, to one decimal, never outside 0 to 100. */
const at = (hub: Hub, seconds: number) => Math.min(100, Math.max(0, Math.round((seconds / hub.cycle) * 1000) / 10))

/** A chip's run within the cycle: out of sight until it sets off, along its hairline, then gone. */
export function chipStops(hub: Hub, leg: Leg): Stop[] {
  const start = leg.delay
  const end = leg.delay + leg.duration
  const fade = leg.side === "in" ? 0.18 : 0.12
  return [
    [0, { "offset-distance": "0%", opacity: 0 }],
    [at(hub, start), { "offset-distance": "0%", opacity: 0 }],
    [at(hub, start + leg.duration * 0.1), { opacity: 1 }],
    [at(hub, end - leg.duration * fade), { opacity: 1 }],
    [at(hub, end), { "offset-distance": "100%", opacity: 0 }],
    [100, { "offset-distance": "100%", opacity: 0 }],
  ]
}

/** A portrait's pop as its event leaves it: a little larger, then back. */
export function popStops(hub: Hub, leaves: number): Stop[] {
  return [
    [0, { transform: "scale(1)" }],
    [at(hub, leaves), { transform: "scale(1)" }],
    [at(hub, leaves + 0.12), { transform: "scale(1.04)" }],
    [at(hub, leaves + 0.4), { transform: "scale(1)" }],
    [100, { transform: "scale(1)" }],
  ]
}

/** The ring that spreads from a portrait and fades as its event leaves it. */
export function rippleStops(hub: Hub, leaves: number): Stop[] {
  return [
    [0, { opacity: 0, transform: "scale(1)" }],
    [at(hub, leaves), { opacity: 0.55, transform: "scale(1)" }],
    [at(hub, leaves + 0.55), { opacity: 0, transform: "scale(1.34)" }],
    [100, { opacity: 0, transform: "scale(1.34)" }],
  ]
}

/** A hairline's brightening while a chip runs along it. */
export function lineStops(hub: Hub, start: number, duration: number): Stop[] {
  return [
    [0, { opacity: 0 }],
    [at(hub, start), { opacity: 0 }],
    [at(hub, start + duration * 0.15), { opacity: 1 }],
    [at(hub, start + duration * 0.85), { opacity: 1 }],
    [at(hub, start + duration + 0.2), { opacity: 0 }],
    [100, { opacity: 0 }],
  ]
}

/** A chip's title, which drops away just before the chip goes into the ghost. */
export function dropStops(hub: Hub, leg: Leg): Stop[] {
  return [
    [0, { opacity: 1 }],
    [at(hub, leg.delay + leg.duration * 0.62), { opacity: 1 }],
    [at(hub, leg.delay + leg.duration * 0.76), { opacity: 0 }],
    [at(hub, hub.cycle - 0.1), { opacity: 0 }],
    [100, { opacity: 1 }],
  ]
}

/** Something that appears at `from` and stays until the cycle's end, when it goes with the rest. */
export function stayStops(hub: Hub, from: number): Stop[] {
  const goes = hub.cycle - LAND_S - 0.2
  return [
    [0, { opacity: 0 }],
    [at(hub, from), { opacity: 0 }],
    [at(hub, from + LAND_S), { opacity: 1 }],
    [at(hub, goes), { opacity: 1 }],
    [at(hub, goes + LAND_S), { opacity: 0 }],
    [100, { opacity: 0 }],
  ]
}

/** The ghost's pleased face: shown for a moment as each chip passes, and through the rest. */
export function faceStops(hub: Hub): Stop[] {
  const stops: Stop[] = [[0, { opacity: 0 }]]
  hub.passes.forEach((pass, index) => {
    stops.push([at(hub, pass - 0.1), { opacity: 0 }], [at(hub, pass - 0.06), { opacity: 1 }])
    if (index < hub.passes.length - 1) stops.push([at(hub, pass + 0.85), { opacity: 1 }], [at(hub, pass + 0.89), { opacity: 0 }])
  })
  const goes = hub.cycle - LAND_S - 0.2
  stops.push([at(hub, goes), { opacity: 1 }], [at(hub, goes + 0.04), { opacity: 0 }], [100, { opacity: 0 }])
  return stops
}

/** One CSS @keyframes rule from its stops. */
export function keyframes(name: string, stops: Stop[]): string {
  const body = stops.map(([percent, values]) => `${percent}%{${Object.entries(values).map(([key, value]) => `${key}:${value}`).join(";")}}`).join("")
  return `@keyframes ${name}{${body}}`
}
