// Hero E's node diagram (after agentic.littleplains.com): an event's parts on one side, hairline
// curves into one outlined ghost, and hairline curves out to Sam's calendars. Short coloured
// segments travel the curves to tell the rule: the time reaches every calendar, the title, place,
// and description reach only the calendar that gets details, and the parts that never cross over
// stop short of the ghost with a small end cap.
//
// Everything here is plain geometry and data, worked out at build time, so the page needs no
// JavaScript to draw the diagram or to start its motion. Two layouts share it: `wide` (parts on
// the left, calendars on the right) and `tall` (parts on top, calendars below) for phones.

export type PartKey =
  | "time"
  | "title"
  | "place"
  | "description"
  | "guests"
  | "organizer"
  | "link"
  | "attachments"
  | "invitations"
export type DestinationKey = "work" | "family" | "personal"
export type Projection = "busy" | "details"

/** How far a part gets: to every calendar, only to one that gets details, or never past the ghost. */
export type Reach = "always" | "details" | "never"

/** The colour a part travels in: the time, a detail, or something that stays home. */
export type Role = "time" | "details" | "stays"

export interface Part {
  key: PartKey
  reach: Reach
  /** Whether its pill is tinted in its role's colour (only the few that tell the story). */
  tinted: boolean
}

/** An event's parts, in the order the diagram lists them. The product's rule, part by part:
 * Busy-Only Projection sends only the time; Details Projection adds the title, description, and
 * place; guests, organizer, meeting links, attachments, and invitations never cross over. */
export const PARTS: readonly Part[] = [
  { key: "time", reach: "always", tinted: true },
  { key: "title", reach: "details", tinted: true },
  { key: "place", reach: "details", tinted: false },
  { key: "description", reach: "details", tinted: false },
  { key: "guests", reach: "never", tinted: true },
  { key: "organizer", reach: "never", tinted: false },
  { key: "link", reach: "never", tinted: true },
  { key: "attachments", reach: "never", tinted: false },
  { key: "invitations", reach: "never", tinted: false },
]

/** Sam's calendars and what each one's rule sends it (as in the Rules mockup). */
export const DESTINATIONS: readonly { key: DestinationKey; projection: Projection }[] = [
  { key: "work", projection: "busy" },
  { key: "family", projection: "busy" },
  { key: "personal", projection: "details" },
]

export function roleOf(part: Part): Role {
  return part.reach === "always" ? "time" : part.reach === "details" ? "details" : "stays"
}

/** Whether a part crosses over to a calendar that receives `projection`. */
export function reaches(part: Part, projection: Projection): boolean {
  return part.reach === "always" || (part.reach === "details" && projection === "details")
}

// Geometry ---------------------------------------------------------------------------------------

export interface Point {
  x: number
  y: number
}

/** A cubic Bézier curve. */
export interface Cubic {
  p0: Point
  p1: Point
  p2: Point
  p3: Point
}

const round = (value: number) => Math.round(value * 100) / 100

export function cubicPath({ p0, p1, p2, p3 }: Cubic): string {
  return `M${round(p0.x)} ${round(p0.y)}C${round(p1.x)} ${round(p1.y)} ${round(p2.x)} ${round(p2.y)} ${round(p3.x)} ${round(p3.y)}`
}

export function pointAt({ p0, p1, p2, p3 }: Cubic, t: number): Point {
  const u = 1 - t
  const a = u * u * u
  const b = 3 * u * u * t
  const c = 3 * u * t * t
  const d = t * t * t
  return { x: a * p0.x + b * p1.x + c * p2.x + d * p3.x, y: a * p0.y + b * p1.y + c * p2.y + d * p3.y }
}

const STEPS = 200

/** The curve's length, measured along many short chords. */
export function arcLength(curve: Cubic): number {
  let length = 0
  let previous = curve.p0
  for (let step = 1; step <= STEPS; step += 1) {
    const point = pointAt(curve, step / STEPS)
    length += Math.hypot(point.x - previous.x, point.y - previous.y)
    previous = point
  }
  return length
}

/** The `t` at which the curve has run `distance` from its start. */
export function tAtLength(curve: Cubic, distance: number): number {
  let length = 0
  let previous = curve.p0
  for (let step = 1; step <= STEPS; step += 1) {
    const point = pointAt(curve, step / STEPS)
    const chord = Math.hypot(point.x - previous.x, point.y - previous.y)
    if (length + chord >= distance) return (step - 1 + (distance - length) / (chord || 1)) / STEPS
    length += chord
    previous = point
  }
  return 1
}

/** The `t` at which a curve that only moves forward along `axis` reaches `value` there. */
export function tWhere(curve: Cubic, axis: "x" | "y", value: number): number {
  const rising = curve.p3[axis] >= curve.p0[axis]
  let low = 0
  let high = 1
  for (let step = 0; step < 40; step += 1) {
    const middle = (low + high) / 2
    const before = rising ? pointAt(curve, middle)[axis] < value : pointAt(curve, middle)[axis] > value
    if (before) low = middle
    else high = middle
  }
  return (low + high) / 2
}

/** The two halves of the curve, cut at `t` (de Casteljau). */
export function splitAt({ p0, p1, p2, p3 }: Cubic, t: number): [Cubic, Cubic] {
  const lerp = (a: Point, b: Point): Point => ({ x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t })
  const a = lerp(p0, p1)
  const b = lerp(p1, p2)
  const c = lerp(p2, p3)
  const ab = lerp(a, b)
  const bc = lerp(b, c)
  const middle = lerp(ab, bc)
  return [
    { p0, p1: a, p2: ab, p3: middle },
    { p0: middle, p1: bc, p2: c, p3 },
  ]
}

/** A curve that leaves `from` and arrives at `to` both along the x axis (wide) or the y axis. */
export function link(from: Point, to: Point, axis: "x" | "y", bend = 0.5): Cubic {
  if (axis === "x") {
    const reach = (to.x - from.x) * bend
    return { p0: from, p1: { x: from.x + reach, y: from.y }, p2: { x: to.x - reach, y: to.y }, p3: to }
  }
  const reach = (to.y - from.y) * bend
  return { p0: from, p1: { x: from.x, y: from.y + reach }, p2: { x: to.x, y: to.y - reach }, p3: to }
}

/** A curve that leaves `from` sideways and turns to arrive at `to` going down. */
export function turnDown(from: Point, to: Point): Cubic {
  return {
    p0: from,
    p1: { x: from.x + (to.x - from.x) * 0.65, y: from.y },
    p2: { x: to.x, y: from.y + (to.y - from.y) * 0.3 },
    p3: to,
  }
}

/**
 * The ghost's outline, after the mark (GhostMark.tsx) drawn as a calendar page: rounded top
 * corners, two binder tabs standing up from the top edge, straight sides, and a hem of three
 * scallops. `x`, `y` is the top-left corner of the page; the hem hangs below `y + height`.
 */
export function ghostOutline(x: number, y: number, width: number, height: number) {
  const radius = Math.min(width, height) * 0.2
  const segment = width / 5
  const sag = segment * 0.42
  const bottom = y + height
  let hem = ""
  // Right to left: down, up, down, up, down, as in the mark.
  for (let index = 0; index < 5; index += 1) {
    const direction = index % 2 === 0 ? 1 : -1
    hem += `q${round(-segment / 2)} ${round(direction * sag)} ${round(-segment)} 0`
  }
  const body =
    `M${round(x)} ${round(y + radius)}` +
    `a${round(radius)} ${round(radius)} 0 0 1 ${round(radius)} ${round(-radius)}` +
    `h${round(width - 2 * radius)}` +
    `a${round(radius)} ${round(radius)} 0 0 1 ${round(radius)} ${round(radius)}` +
    `V${round(bottom)}` +
    hem +
    "Z"
  const tab = Math.max(10, height * 0.12)
  const tabs = [0.3, 0.7].map((at) => `M${round(x + width * at)} ${round(y - tab * 0.55)}v${round(tab)}`).join("")
  return { body, tabs, hemDepth: sag / 2 }
}

// Layouts ----------------------------------------------------------------------------------------

export type LayoutKind = "wide" | "tall"

export interface Box {
  x: number
  y: number
  width: number
  height: number
}

export interface PartPill extends Box {
  key: PartKey
  role: Role
  tinted: boolean
}

export interface DestinationPill extends Box {
  key: DestinationKey
  projection: Projection
}

/** One travelling segment: the stretch of one curve it runs, and when. */
export interface Leg {
  part: PartKey
  /** The calendar it runs to, for a leg after the ghost. */
  to?: DestinationKey
  role: Role
  /** The path it runs (for a part that stays home, the curve cut short at its stop). */
  d: string
  /** The path's length. */
  length: number
  /** When it sets off, in seconds from the start of the loop. */
  delay: number
  /** Where it rests in the still diagram: its tail's distance along the path, or null when the
   * still diagram does not show it. */
  still: number | null
}

/** Where a part that never crosses over stops: the last stretch of its segment and a small cap
 * across the curve. */
export interface Stop {
  part: PartKey
  stub: string
  cap: string
  /** When the segment reaches it, in seconds from the start of the loop. */
  delay: number
}

export interface Diagram {
  kind: LayoutKind
  width: number
  height: number
  parts: PartPill[]
  destinations: DestinationPill[]
  /** The ghost: its outline, its tabs, and where its name sits. */
  node: { body: string; tabs: string; center: Point; eyes: [Point, Point] }
  /** The hairlines, one per part and one per calendar. */
  curves: { id: string; d: string }[]
  /** The short strokes from each hub into the ghost. */
  stubs: string
  legs: Leg[]
  stops: Stop[]
}

/** The loop's length in seconds. Every part sets off once per loop. */
export const CYCLE_S = 16
/** How fast a segment travels, in diagram units per second. */
export const SPEED = 130
/** A travelling segment's length, in diagram units. */
export const SEGMENT = 26
/** How long a segment spends inside the ghost before it leaves on the other side. */
export const THROUGH_S = 0.35
/** When each part sets off: the time first, then the parts that stay and the details in turn. */
export const STARTS: Record<PartKey, number> = {
  time: 0.4,
  guests: 2,
  title: 3.6,
  link: 5.2,
  place: 6.8,
  organizer: 8.4,
  description: 10,
  attachments: 11.6,
  invitations: 13.2,
}

/** Where the still diagram rests each crossing part's segment, as a share of its curve, a little
 * apart so the frozen moment reads as motion caught mid-way. */
const STILL_AT: Record<LayoutKind, Partial<Record<PartKey, number>>> = {
  wide: { time: 0.58, title: 0.4, place: 0.66, description: 0.5 },
  tall: { time: 0.3, title: 0.18, place: 0.36, description: 0.24 },
}

/** The dash pattern a leg needs: one segment, then a gap longer than everything it runs in a loop. */
export function dashFor(leg: Leg) {
  const travel = SPEED * CYCLE_S
  return {
    dasharray: `${SEGMENT} ${round(travel + leg.length)}`,
    /** The segment just before the path's start, out of sight. */
    from: SEGMENT,
    /** Where a loop leaves it: long past the path's end. */
    to: round(SEGMENT - travel),
    /** The still diagram's position, or out of sight. */
    still: leg.still === null ? SEGMENT : round(-leg.still),
  }
}

interface Frame {
  width: number
  height: number
  parts: PartPill[]
  destinations: DestinationPill[]
  node: Box
  hubIn: Point
  hubOut: Point
  /** Where each hub's stub meets the ghost. */
  entry: Point
  exit: Point
  partCurve: (pill: PartPill) => Cubic
  destinationCurve: (pill: DestinationPill) => Cubic
  /** The line a part that stays home stops at, short of the hub: a vertical line at `x` (wide)
   * or a horizontal one at `y` (tall), so the stops stand in a row like a closed gate. */
  gate: { axis: "x" | "y"; at: number }
}

function wideFrame(): Frame {
  const width = 1040
  const pill = { width: 132, height: 34, pitch: 46 }
  const top = 14
  const height = top * 2 + PARTS.length * pill.pitch - (pill.pitch - pill.height)
  const middle = height / 2
  const parts = PARTS.map((part, index) => ({
    key: part.key,
    role: roleOf(part),
    tinted: part.tinted,
    x: 0.5,
    y: top + index * pill.pitch,
    width: pill.width,
    height: pill.height,
  }))
  const destination = { width: 196, height: 34, pitch: 66 }
  const destinations = DESTINATIONS.map((item, index) => ({
    ...item,
    x: width - destination.width - 0.5,
    y: middle - destination.height / 2 + (index - 1) * destination.pitch,
    width: destination.width,
    height: destination.height,
  }))
  const node = { width: 232, height: 168 }
  const nodeBox = { x: (width - node.width) / 2 - 8, y: middle - node.height / 2, width: node.width, height: node.height }
  const entry = { x: nodeBox.x, y: middle }
  const exit = { x: nodeBox.x + nodeBox.width, y: middle }
  const hubIn = { x: entry.x - 14, y: middle }
  const hubOut = { x: exit.x + 6, y: middle }
  return {
    width,
    height,
    parts,
    destinations,
    node: nodeBox,
    hubIn,
    hubOut,
    entry,
    exit,
    partCurve: (pill) => link({ x: pill.x + pill.width, y: pill.y + pill.height / 2 }, hubIn, "x"),
    destinationCurve: (pill) => link(hubOut, { x: pill.x, y: pill.y + pill.height / 2 }, "x"),
    gate: { axis: "x", at: hubIn.x - 150 },
  }
}

function tallFrame(): Frame {
  const width = 340
  const pill = { width: 118, height: 30, pitch: 40 }
  const top = 4
  // The parts that cross over on the left, the ones that stay home on the right, curving into the
  // ghost's top between them.
  const left = PARTS.filter((part) => part.reach !== "never")
  const right = PARTS.filter((part) => part.reach === "never")
  const columnHeight = (count: number) => count * pill.pitch - (pill.pitch - pill.height)
  const tallest = Math.max(columnHeight(left.length), columnHeight(right.length))
  const place = (column: Part[], x: number) =>
    column.map((part, index) => ({
      key: part.key,
      role: roleOf(part),
      tinted: part.tinted,
      x,
      y: top + (tallest - columnHeight(column.length)) / 2 + index * pill.pitch,
      width: pill.width,
      height: pill.height,
    }))
  const parts = [...place(left, 0.5), ...place(right, width - pill.width - 0.5)].sort(
    (a, b) => PARTS.findIndex((part) => part.key === a.key) - PARTS.findIndex((part) => part.key === b.key),
  )
  const center = width / 2
  const hubIn = { x: center, y: top + tallest + 72 }
  const node = { width: 176, height: 112 }
  const nodeBox = { x: center - node.width / 2, y: hubIn.y + 8, width: node.width, height: node.height }
  const entry = { x: center, y: nodeBox.y }
  const { hemDepth } = ghostOutline(nodeBox.x, nodeBox.y, nodeBox.width, nodeBox.height)
  const exit = { x: center, y: nodeBox.y + nodeBox.height + hemDepth }
  const hubOut = { x: center, y: exit.y + 8 }
  const destination = { width: 106, height: 46, gap: (width - 1 - 3 * 106) / 2 }
  const destinationsTop = hubOut.y + 64
  const destinations = DESTINATIONS.map((item, index) => ({
    ...item,
    x: 0.5 + index * (destination.width + destination.gap),
    y: destinationsTop,
    width: destination.width,
    height: destination.height,
  }))
  return {
    width,
    height: destinationsTop + destination.height + 1,
    parts,
    destinations,
    node: nodeBox,
    hubIn,
    hubOut,
    entry,
    exit,
    partCurve: (pill) => {
      const fromLeft = pill.x < center
      return turnDown({ x: fromLeft ? pill.x + pill.width : pill.x, y: pill.y + pill.height / 2 }, hubIn)
    },
    destinationCurve: (pill) => link(hubOut, { x: pill.x + pill.width / 2, y: pill.y }, "y"),
    gate: { axis: "x", at: center + 16 },
  }
}

/** Builds one layout of the diagram: its boxes, its hairlines, and its travelling segments. */
export function buildDiagram(kind: LayoutKind): Diagram {
  const frame = kind === "wide" ? wideFrame() : tallFrame()
  const curves: Diagram["curves"] = []
  const legs: Leg[] = []
  const stops: Stop[] = []
  const destinationCurves = new Map(frame.destinations.map((pill) => [pill.key, frame.destinationCurve(pill)]))

  for (const pill of frame.destinations) curves.push({ id: `to-${pill.key}`, d: cubicPath(destinationCurves.get(pill.key)!) })

  let firstDetail = true
  for (const pill of frame.parts) {
    const part = PARTS.find((item) => item.key === pill.key)!
    const role = roleOf(part)
    const curve = frame.partCurve(pill)
    const length = arcLength(curve)
    const delay = STARTS[part.key]
    curves.push({ id: `from-${part.key}`, d: cubicPath(curve) })

    if (part.reach === "never") {
      // The segment runs the curve cut short of the hub, and is swallowed at the cut; at that
      // moment its last stretch and the cap show where it stopped.
      const [short] = splitAt(curve, tWhere(curve, frame.gate.axis, frame.gate.at))
      const reach = arcLength(short)
      const [, stub] = splitAt(short, tAtLength(short, reach - SEGMENT))
      const end = short.p3
      // The cap lies along the gate, so the stops line up like a closed gate.
      const across = frame.gate.axis === "x" ? { x: 0, y: 4.5 } : { x: 4.5, y: 0 }
      legs.push({ part: part.key, role, d: cubicPath(short), length: reach, delay, still: null })
      stops.push({
        part: part.key,
        stub: cubicPath(stub),
        cap: `M${round(end.x - across.x)} ${round(end.y - across.y)}L${round(end.x + across.x)} ${round(end.y + across.y)}`,
        delay: round(delay + reach / SPEED),
      })
      continue
    }

    legs.push({ part: part.key, role, d: cubicPath(curve), length, delay, still: (length - SEGMENT) * (STILL_AT[kind][part.key] ?? 0.5) })
    const onward = round(delay + length / SPEED + THROUGH_S)
    for (const destination of frame.destinations) {
      if (!reaches(part, destination.projection)) continue
      const out = destinationCurves.get(destination.key)!
      const outLength = arcLength(out)
      // The still diagram shows the time on every calendar's curve and one detail on the one that
      // gets details, further along.
      const still = role === "time" ? (outLength - SEGMENT) * 0.6 : firstDetail ? (outLength - SEGMENT) * 0.84 : null
      legs.push({ part: part.key, to: destination.key, role, d: cubicPath(out), length: outLength, delay: onward, still })
    }
    if (role === "details") firstDetail = false
  }

  const { body, tabs } = ghostOutline(frame.node.x, frame.node.y, frame.node.width, frame.node.height)
  const center = { x: frame.node.x + frame.node.width / 2, y: frame.node.y + frame.node.height / 2 }
  const eyeGap = frame.node.width * 0.07
  const eyeY = frame.node.y + frame.node.height * 0.24
  return {
    kind,
    width: frame.width,
    height: frame.height,
    parts: frame.parts,
    destinations: frame.destinations,
    node: { body, tabs, center, eyes: [{ x: center.x - eyeGap, y: eyeY }, { x: center.x + eyeGap, y: eyeY }] },
    curves,
    stubs:
      `M${round(frame.hubIn.x)} ${round(frame.hubIn.y)}L${round(frame.entry.x)} ${round(frame.entry.y)}` +
      `M${round(frame.exit.x)} ${round(frame.exit.y)}L${round(frame.hubOut.x)} ${round(frame.hubOut.y)}`,
    legs,
    stops,
  }
}
