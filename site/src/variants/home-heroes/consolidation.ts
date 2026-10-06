// Hero E2's diagram, in hero E's style (node-diagram.ts) but telling the product's real story:
// Sam's many calendars on one side, hairlines into the outlined ghost, and Sam's one Work calendar
// on the other side as a day column. A short segment leaves each calendar in that calendar's
// colour, enters the ghost, and leaves it in Lantern Indigo; where it lands, a "Busy" block
// appears at its event's time, beside Work's own meeting. The day it shows is Sam's Monday, as in
// the rest of the page (demo/week.ts).
//
// Everything here is plain geometry and data, worked out at build time, so the page draws the
// diagram, and starts its motion, without JavaScript. Two layouts share it: `wide` (calendars on
// the left, Work on the right) and `tall` (calendars on top, Work below) for phones.

import type { Calendar } from "../../avatars"
import { DAY_END, DAY_START, SAM_WEEK } from "../../demo/week"
import { arcLength, cubicPath, ghostOutline, link, turnDown, type Box, type Cubic, type Point } from "./node-diagram"

export type SourceKey = "personal" | "family" | "kidsSchool" | "runningClub" | "sideProject"

/** Monday's events from Sam's week (demo/week.ts) that the diagram shows. */
export type WeekEventKey = "dentist" | "standup"
/** Events of Sam's that the rest of the page does not show, because they fall outside the week's
 * hours (DAY_START to DAY_END), so they never contradict it. */
export type ExtraEventKey = "familyDinner" | "schoolPlay" | "morningRun" | "launchCall"

export interface TimedEvent {
  key: WeekEventKey | ExtraEventKey
  /** Hours, so 15.5 is 15:30. */
  start: number
  end: number
}

/** One of Sam's calendars that copies its events to Work as Busy. */
export interface Source {
  key: SourceKey
  /** Sam's portrait for the calendar's account, or null where it would repeat one already shown
   * (the calendar then shows a small dot in its own colour). */
  avatar: Calendar | null
  /** Its one event on the day the diagram shows. */
  event: TimedEvent
}

function monday(key: WeekEventKey): TimedEvent {
  const event = SAM_WEEK.find((item) => item.key === key && item.day === 0)
  if (!event) throw new Error(`Sam's Monday has no ${key}`)
  return { key, start: event.start, end: event.end }
}

/** Sam's calendars, in the order the diagram lists them. */
export const SOURCES: readonly Source[] = [
  { key: "personal", avatar: "personal", event: monday("dentist") },
  { key: "family", avatar: "family", event: { key: "familyDinner", start: 18.5, end: 19.5 } },
  { key: "kidsSchool", avatar: null, event: { key: "schoolPlay", start: 17, end: 18 } },
  { key: "runningClub", avatar: null, event: { key: "morningRun", start: 7.5, end: 8.5 } },
  { key: "sideProject", avatar: null, event: { key: "launchCall", start: 20, end: 21 } },
]

/** Work's own meetings that day: they stay as they are. */
export const WORK_MEETINGS: readonly TimedEvent[] = [monday("standup")]

/** The hours the Work column shows. */
export const HOURS = { start: 7, end: 21 } as const

/** A clock time, as "07:30". */
export function clock(hours: number): string {
  const whole = Math.floor(hours)
  const minutes = Math.round((hours - whole) * 60)
  return `${String(whole).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`
}

/** Whether an event falls inside the hours the week (demo/week.ts) shows. */
export function inWeekHours(event: TimedEvent): boolean {
  return event.end > DAY_START && event.start < DAY_END
}

// Motion ----------------------------------------------------------------------------------------

/** How fast a segment travels, in diagram units per second. */
export const SPEED = 130
/** A travelling segment's length, in diagram units. */
export const SEGMENT = 26
/** How long a segment spends inside the ghost before it leaves as Busy. */
export const THROUGH_S = 0.35
/** How long a Busy block takes to appear. */
export const APPEAR_S = 0.45
/** How long a calendar's pill stays tinted around its segment's departure. */
export const TINT_S = 1.8

/** When each calendar's segment sets off, in seconds from the first paint. Personal (the Dentist)
 * is already on its way, so the first Busy lands within about two seconds; the rest follow one at
 * a time, so a few segments are in flight at once. */
export const DEPARTS: Record<SourceKey, number> = {
  personal: -1,
  runningClub: 0.3,
  kidsSchool: 1.6,
  family: 2.9,
  sideProject: 4.2,
}

// Layouts ----------------------------------------------------------------------------------------

export type LayoutKind = "wide" | "tall"

export interface SourcePill extends Box {
  key: SourceKey
  avatar: Calendar | null
  event: TimedEvent
}

/** A block in the Work column: one of Work's own meetings, or a Busy block from a calendar. */
export interface Slot extends Box {
  event: TimedEvent
  /** The calendar a Busy block comes from; absent for Work's own meeting. */
  source?: SourceKey
  /** When a Busy block appears, in seconds from the first paint. */
  appears?: number
}

/** One travelling segment: the path it runs and when. */
export interface Leg {
  source: SourceKey
  /** Into the ghost (in the calendar's colour) or out of it (as Busy). */
  side: "in" | "out"
  d: string
  length: number
  /** When it sets off, in seconds from the first paint (negative: already on its way). */
  delay: number
  /** How long it takes to run its path, tail included. */
  duration: number
}

export interface Diagram {
  kind: LayoutKind
  width: number
  height: number
  /** Where the two quiet labels start: over the calendars, and over Work. */
  labels: { calendars: Point; work: Point }
  sources: SourcePill[]
  node: { body: string; tabs: string; center: Point; eyes: [Point, Point] }
  /** The short strokes from each hub into and out of the ghost. */
  stubs: string
  curves: { id: string; d: string }[]
  /** Work's outlined node: its box, and the height of its header (portrait, name, account). */
  work: Box & { header: number }
  /** Faint lines across the column, one per hour, as in a calendar's day view. */
  hourLines: number[]
  slots: Slot[]
  legs: Leg[]
}

/** The dash pattern a leg needs: one segment, then a gap longer than the whole path. */
export function dashFor(leg: Leg) {
  const round = (value: number) => Math.round(value * 100) / 100
  return {
    dasharray: `${SEGMENT} ${round(leg.length + SEGMENT * 2)}`,
    /** Just before the path's start, out of sight (also the still diagram's position). */
    from: SEGMENT,
    /** Just past the path's end, out of sight. */
    to: round(-leg.length),
  }
}

interface Frame {
  width: number
  height: number
  labels: Diagram["labels"]
  sources: SourcePill[]
  node: Box
  hubIn: Point
  hubOut: Point
  entry: Point
  exit: Point
  work: Diagram["work"]
  /** The column's top and the height of one hour in it. */
  column: { top: number; hour: number; inset: number }
  sourceCurve: (pill: SourcePill) => Cubic
  /** Each Busy block's curve from the ghost; the tall layout has one curve for all of them. */
  slotCurve: (slot: Slot) => Cubic
  shared: boolean
}

function wideFrame(): Frame {
  const width = 1040
  const top = 30
  const hour = 22
  const header = 52
  const columnTop = top + header + 10
  const columnHeight = (HOURS.end - HOURS.start) * hour
  const workHeight = header + 10 + columnHeight + 10
  const work = { x: width - 268 - 0.5, y: top, width: 268, height: workHeight, header }
  const height = Math.ceil(top + workHeight + 1)
  const middle = top + workHeight / 2
  const pill = { width: 214, height: 54, pitch: 70 }
  const stack = SOURCES.length * pill.pitch - (pill.pitch - pill.height)
  const sources = SOURCES.map((source, index) => ({
    ...source,
    x: 0.5,
    y: middle - stack / 2 + index * pill.pitch,
    width: pill.width,
    height: pill.height,
  }))
  const node = { width: 184, height: 132 }
  const nodeBox = { x: 400, y: middle - node.height / 2 - 4, width: node.width, height: node.height }
  const entry = { x: nodeBox.x, y: middle }
  const exit = { x: nodeBox.x + nodeBox.width, y: middle }
  const hubIn = { x: entry.x - 14, y: middle }
  const hubOut = { x: exit.x + 6, y: middle }
  return {
    width,
    height,
    labels: { calendars: { x: 0.5, y: middle - stack / 2 - 21 }, work: { x: work.x, y: 9 } },
    sources,
    node: nodeBox,
    hubIn,
    hubOut,
    entry,
    exit,
    work,
    column: { top: columnTop, hour, inset: 10 },
    sourceCurve: (item) => link({ x: item.x + item.width, y: item.y + item.height / 2 }, hubIn, "x"),
    slotCurve: (slot) => link(hubOut, { x: work.x, y: slot.y + slot.height / 2 }, "x"),
    shared: false,
  }
}

/** Where each calendar sits on a phone: Personal, Kids' school, and Side project on the left;
 * Family and Running club on the right, half a row lower. */
const TALL_PLACES: Record<SourceKey, { column: 0 | 1; row: number }> = {
  personal: { column: 0, row: 0 },
  family: { column: 1, row: 0.5 },
  kidsSchool: { column: 0, row: 1 },
  runningClub: { column: 1, row: 1.5 },
  sideProject: { column: 0, row: 2 },
}

function tallFrame(): Frame {
  const width = 300
  const center = width / 2
  const pill = { width: 128, height: 40, pitch: 48 }
  const top = 22
  const sources = SOURCES.map((source) => {
    const place = TALL_PLACES[source.key]
    return {
      ...source,
      x: place.column === 0 ? 0.5 : width - pill.width - 0.5,
      y: top + place.row * pill.pitch,
      width: pill.width,
      height: pill.height,
    }
  })
  const bottom = Math.max(...sources.map((item) => item.y + item.height))
  const hubIn = { x: center, y: bottom + 44 }
  const node = { width: 124, height: 80 }
  const nodeBox = { x: center - node.width / 2, y: hubIn.y + 8, width: node.width, height: node.height }
  const { hemDepth } = ghostOutline(nodeBox.x, nodeBox.y, nodeBox.width, nodeBox.height)
  const entry = { x: center, y: nodeBox.y }
  const exit = { x: center, y: nodeBox.y + nodeBox.height + hemDepth }
  const hubOut = { x: center, y: exit.y + 8 }
  const hour = 18
  const header = 46
  const workTop = hubOut.y + 34
  const columnHeight = (HOURS.end - HOURS.start) * hour
  const workHeight = header + 8 + columnHeight + 8
  const work = { x: 0.5, y: workTop, width: width - 1, height: workHeight, header }
  return {
    width,
    height: Math.ceil(workTop + workHeight + 1),
    labels: { calendars: { x: 0.5, y: 8 }, work: { x: 0.5, y: workTop - 12 } },
    sources,
    node: nodeBox,
    hubIn,
    hubOut,
    entry,
    exit,
    work,
    column: { top: workTop + header + 8, hour, inset: 8 },
    sourceCurve: (item) => {
      const fromLeft = item.x < center
      return turnDown({ x: fromLeft ? item.x + item.width : item.x, y: item.y + item.height / 2 }, hubIn)
    },
    slotCurve: () => link(hubOut, { x: center, y: workTop }, "y"),
    shared: true,
  }
}

/** Builds one layout of the diagram: its boxes, its hairlines, and its travelling segments. */
export function buildDiagram(kind: LayoutKind): Diagram {
  const frame = kind === "wide" ? wideFrame() : tallFrame()
  const { column, work } = frame
  const block = (event: TimedEvent): Box => ({
    x: work.x + column.inset,
    y: column.top + (event.start - HOURS.start) * column.hour + 1,
    width: work.width - column.inset * 2,
    height: (event.end - event.start) * column.hour - 2,
  })

  const curves: Diagram["curves"] = []
  const legs: Leg[] = []
  const slots: Slot[] = WORK_MEETINGS.map((event) => ({ ...block(event), event }))
  if (frame.shared) curves.push({ id: "to-work", d: cubicPath(frame.slotCurve(slots[0]!)) })

  for (const pill of frame.sources) {
    const into = frame.sourceCurve(pill)
    const inLength = arcLength(into)
    const departs = DEPARTS[pill.key]
    curves.push({ id: `from-${pill.key}`, d: cubicPath(into) })
    legs.push({ source: pill.key, side: "in", d: cubicPath(into), length: inLength, delay: departs, duration: (inLength + SEGMENT) / SPEED })

    const slot: Slot = { ...block(pill.event), event: pill.event, source: pill.key }
    const out = frame.slotCurve(slot)
    const outLength = arcLength(out)
    const leaves = departs + inLength / SPEED + THROUGH_S
    if (!frame.shared) curves.push({ id: `to-${pill.key}`, d: cubicPath(out) })
    legs.push({ source: pill.key, side: "out", d: cubicPath(out), length: outLength, delay: leaves, duration: (outLength + SEGMENT) / SPEED })
    slots.push({ ...slot, appears: Math.round((leaves + outLength / SPEED) * 100) / 100 })
  }

  const hourLines: number[] = []
  for (let hour = HOURS.start + 1; hour < HOURS.end; hour += 1) hourLines.push(column.top + (hour - HOURS.start) * column.hour)

  const { body, tabs } = ghostOutline(frame.node.x, frame.node.y, frame.node.width, frame.node.height)
  const center = { x: frame.node.x + frame.node.width / 2, y: frame.node.y + frame.node.height / 2 }
  const eyeGap = frame.node.width * 0.07
  const eyeY = frame.node.y + frame.node.height * 0.24
  const r = (value: number) => Math.round(value * 100) / 100
  return {
    kind,
    width: frame.width,
    height: frame.height,
    labels: frame.labels,
    sources: frame.sources,
    node: { body, tabs, center, eyes: [{ x: center.x - eyeGap, y: eyeY }, { x: center.x + eyeGap, y: eyeY }] },
    stubs:
      `M${r(frame.hubIn.x)} ${r(frame.hubIn.y)}L${r(frame.entry.x)} ${r(frame.entry.y)}` +
      `M${r(frame.exit.x)} ${r(frame.exit.y)}L${r(frame.hubOut.x)} ${r(frame.hubOut.y)}`,
    curves,
    work,
    hourLines,
    slots,
    legs,
  }
}
