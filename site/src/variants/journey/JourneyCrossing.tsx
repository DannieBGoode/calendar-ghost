import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react"
import type { AvatarUrls } from "../../avatars"
import type { Messages } from "../../i18n"
import { iconMarkup, type IconName } from "../../icons"
import { Ghost, SpeechBubble } from "../../islands/Ghost"
import { useHydrated, useOnScreen, usePageVisible, useReducedMotion } from "../../islands/hooks"
import { MotionToggle } from "../../islands/MotionToggle"
import {
  DENTIST_TIME,
  MODES,
  RUN,
  WORK_HOURS,
  clock,
  easeInOut,
  easeOut,
  momentAt,
  peelWindow,
  progress,
  staysBehind,
  type CrossingMode,
  type Part,
  type PlanText,
} from "./crossing"

/** The icon beside each part of the plan, as in Google Calendar's event details. */
const PART_ICONS: Record<Exclude<Part, "title">, IconName> = {
  time: "clock",
  place: "mapPin",
  description: "alignLeft",
  guests: "users",
  link: "video",
}
/** Where the first run starts: on the landed state the page already shows, a few seconds before
 * the ghost flies back for the next trip. */
const FIRST_MS = 7200
/** How high the ghost holds the plan over its slot before setting it down. */
const LIFT_PX = 16

function PartIcon({ part }: { part: Exclude<Part, "title"> }) {
  return <span className="jc-icon" dangerouslySetInnerHTML={{ __html: iconMarkup(PART_ICONS[part], "jc-icon-svg") }} />
}

/** The plan as Sam's own calendar shows it: the card, then its guests and meeting link. */
function PlanCard({ plan, when, busy }: { plan: PlanText; when: string; busy?: string }) {
  return (
    <>
      <div className="jc-card">
        <span className="jc-part jc-title" data-part="title">
          {plan.title}
        </span>
        {(["time", "place", "description"] as const).map((part) => (
          <span key={part} className="jc-part jc-row" data-part={part}>
            <PartIcon part={part} />
            <span>{part === "time" ? when : plan[part]}</span>
          </span>
        ))}
        {busy ? (
          <span className="jc-card-busy" data-busy>
            <b>{busy}</b>
            <span className="jc-part jc-row">
              <PartIcon part="time" />
              <span>{when}</span>
            </span>
          </span>
        ) : null}
      </div>
      <span className="jc-attach">
        {(["guests", "link"] as const).map((part) => (
          <span key={part} className="jc-part jc-pill" data-part={part}>
            <PartIcon part={part} />
            <span>{plan[part]}</span>
          </span>
        ))}
      </span>
    </>
  )
}

type Box = { x: number; y: number; w: number; h: number }

/** An element's layout box inside `stage`, ignoring transforms (so it can be measured mid-run). */
function boxIn(element: HTMLElement, stage: HTMLElement): Box {
  let x = 0
  let y = 0
  let node: HTMLElement | null = element
  while (node && node !== stage) {
    x += node.offsetLeft
    y += node.offsetTop
    node = node.offsetParent as HTMLElement | null
  }
  return { x, y, w: element.offsetWidth, h: element.offsetHeight }
}

interface Geometry {
  source: Box
  landed: Box
  rest: Box
  /** The card's own height, without the guests and link under it. */
  cardH: number
  /** Whether the plan crosses sideways (wide screens) or down (phones). */
  across: boolean
  /** Where the ghost draws its copy out to, from on top of Sam's plan. */
  take: { x: number; y: number }
}

const lerp = (from: number, to: number, t: number) => from + (to - from) * t

export interface JourneyCrossingCopy {
  switchLabel: string
  busyOnly: string
  withDetails: string
  busyOnlyBody: string
  withDetailsBody: string
  peel: string
  busySays: string
  detailsSays: string
  busy: string
  summary: string
  day: string
  calendars: Messages["demo"]["calendars"]
  motion: Messages["motion"]
}

/**
 * The /journey hero: pick what crosses over, then watch the ghost carry Sam's Dentist appointment
 * from Personal to Work. The parts that never cross peel off its copy and fly home.
 *
 * The landed result is plain CSS driven by the radio buttons, so it is right without JavaScript
 * and under reduced motion. With JavaScript, each run is an overlay on that result: it starts and
 * ends on it, and clears its inline styles when it stops.
 */
export function JourneyCrossing({
  m,
  plan,
  avatars,
  compactToggle = false,
  firstRestMs = RUN.total - FIRST_MS,
}: {
  m: JourneyCrossingCopy
  plan: PlanText
  avatars: AvatarUrls
  /** Show the pause control as a 44px icon button (the home hero iteration B uses it). */
  compactToggle?: boolean
  /** How long the landed state holds before the first run (default 2.8 seconds). */
  firstRestMs?: number
}) {
  const root = useRef<HTMLDivElement>(null)
  const source = useRef<HTMLDivElement>(null)
  const traveler = useRef<HTMLDivElement>(null)
  const landedSlot = useRef<HTMLDivElement>(null)
  const ghost = useRef<HTMLDivElement>(null)
  const [mode, setMode] = useState<CrossingMode>("busy")
  const [paused, setPaused] = useState(false)
  const hydrated = useHydrated()
  const reducedMotion = useReducedMotion()
  const onScreen = useOnScreen(root)
  const pageVisible = usePageVisible()
  const running = hydrated && !reducedMotion && onScreen && pageVisible && !paused
  const stays = staysBehind(mode)
  const when = `${m.day} ${clock(DENTIST_TIME.start)}–${clock(DENTIST_TIME.end)}`

  // The run's clock survives pauses; `restart` marks that the ghost may be mid-air and should
  // fade in at its resting place instead of jumping there.
  const clockMs = useRef(RUN.total - firstRestMs)
  const restart = useRef(false)
  const geometry = useRef<Geometry | null>(null)
  const touched = useRef(new Set<HTMLElement>())

  const style = useCallback((element: HTMLElement | null | undefined, transform: string, opacity?: number) => {
    if (!element) return
    touched.current.add(element)
    element.style.transform = transform
    if (opacity !== undefined) element.style.opacity = String(opacity)
  }, [])

  /** Back to the plain landed state: no inline styles, no moment. */
  const clear = useCallback(() => {
    for (const element of touched.current) {
      element.style.transform = ""
      element.style.opacity = ""
    }
    touched.current.clear()
    delete root.current?.dataset.moment
    geometry.current = null
  }, [])

  const measure = useCallback((): Geometry | null => {
    const stageEl = root.current
    const sourceEl = source.current
    const travelerEl = traveler.current
    const ghostEl = ghost.current
    const landedEl = landedSlot.current?.querySelector<HTMLElement>(`[data-mode="${mode}"]`)
    if (!stageEl || !sourceEl || !travelerEl || !ghostEl || !landedEl) return null
    const from = boxIn(sourceEl, stageEl)
    const landed = boxIn(landedEl, stageEl)
    // The traveler starts exactly over Sam's plan, with the same width, so taking hold of it
    // changes nothing on screen.
    travelerEl.style.left = `${from.x}px`
    travelerEl.style.top = `${from.y}px`
    travelerEl.style.width = `${from.w}px`
    const across = Math.abs(landed.x - from.x) > Math.abs(landed.y - from.y)
    const take = across
      ? { x: Math.min(from.w + 28, (landed.x - from.x) * 0.45), y: 8 }
      : { x: 0, y: Math.min(from.h + 12, (landed.y - from.y) * 0.6) }
    const cardH = travelerEl.querySelector<HTMLElement>(".jc-card")?.offsetHeight ?? from.h
    return { source: from, landed, rest: boxIn(ghostEl, stageEl), cardH, across, take }
  }, [mode])

  const apply = useCallback(
    (ms: number) => {
      const rootEl = root.current
      const travelerEl = traveler.current
      const ghostEl = ghost.current
      if (!rootEl || !travelerEl || !ghostEl) return
      if (!geometry.current) geometry.current = measure()
      const geo = geometry.current
      if (!geo) return
      const moment = momentAt(ms)
      if (rootEl.dataset.moment !== moment) rootEl.dataset.moment = moment

      const { source: from, landed, rest, take, across, cardH } = geo
      const dx = landed.x - from.x
      const dy = landed.y - from.y
      const scale = landed.w / from.w
      const fetchOut = 1 - progress(ms, [RUN.fetch[0], RUN.fetch[0] + 450])

      // The ghost's copy: drawn out into the open, carried along an arc, squashed into its slot.
      const drawn = easeInOut(progress(ms, RUN.take))
      let tx = take.x * drawn
      let ty = take.y * drawn
      let sx = 1
      let sy = 1
      const carry = easeInOut(progress(ms, RUN.carry))
      if (carry > 0) {
        const arc = Math.sin(Math.PI * carry) * (across ? 34 : 30)
        tx = lerp(take.x, dx, carry) + (across ? 0 : arc)
        ty = lerp(take.y, dy - LIFT_PX, carry) - (across ? arc : 0)
        sx = sy = lerp(1, scale, carry)
      }
      const set = easeInOut(progress(ms, RUN.set))
      if (set > 0) {
        tx = dx
        ty = dy - LIFT_PX * (1 - set)
        sx = scale
        sy = lerp(scale, landed.h / cardH, set)
      }
      const shown = ms >= RUN.take[0] && ms < RUN.set[1]
      style(travelerEl, `translate(${tx}px, ${ty}px) scale(${sx}, ${sy})`, shown ? 1 - progress(ms, [RUN.set[0] + 200, RUN.set[1]]) : 0)

      // The parts that stay behind peel off the copy and fly home to Sam's own plan, which never
      // changed; each one lands on its twin there and disappears into it.
      stays.forEach((part, index) => {
        const element = travelerEl.querySelector<HTMLElement>(`[data-part="${part}"]`)
        const flight = progress(ms, peelWindow(index))
        const eased = easeInOut(flight)
        const hop = Math.sin(Math.PI * flight)
        const turn = (index % 2 === 0 ? -1 : 1) * 12 * hop
        const x = -take.x * eased + (across ? 0 : 26 * hop)
        const y = -take.y * eased - (across ? 22 * hop : 0)
        style(element, `translate(${x}px, ${y}px) rotate(${turn}deg)`, flight < 1 ? 1 - progress(flight, [0.82, 1]) : 0)
      })
      // With Busy only, once the title has gone home the copy shows "Busy" in its place.
      const busyOverlay = travelerEl.querySelector<HTMLElement>("[data-busy]")
      if (busyOverlay) {
        const titleHome = peelWindow(0)[1]
        style(busyOverlay, "", progress(ms, [titleHome - 300, titleHome + 100]))
      }

      // The plan's place on Work: there from the last run, gone while the ghost fetches the next.
      const arrive = progress(ms, [RUN.set[0] + 200, RUN.set[1]])
      style(landedSlot.current, ms >= RUN.set[0] && arrive < 1 ? `scale(${0.96 + 0.04 * arrive})` : "", ms < RUN.fetch[1] ? fetchOut : arrive)

      // The ghost: back to the plan, holding the copy by its top edge on the way, then back to rest.
      const gripAt = (box: Box, x: number, y: number, s: number) => ({
        x: box.x + x + box.w * s - rest.w * 0.62 - rest.x,
        y: box.y + y - rest.h * 0.6 - rest.y,
      })
      const held = gripAt(from, tx, ty, sx)
      let gx = held.x
      let gy = held.y
      if (ms < RUN.take[0]) {
        const back = easeInOut(progress(ms, RUN.fetch))
        const target = gripAt(from, 0, 0, 1)
        gx = lerp(0, target.x, back)
        gy = lerp(0, target.y, back) - Math.sin(Math.PI * back) * 30
      } else if (ms >= RUN.settle[0]) {
        const home = easeOut(progress(ms, RUN.settle))
        const start = gripAt(landed, 0, 0, 1)
        gx = lerp(start.x, 0, home)
        gy = lerp(start.y, 0, home)
      }
      style(ghostEl, `translate(${gx}px, ${gy}px)`, restart.current ? progress(ms, [0, 250]) : 1)
      // A little wave goodbye to what stays home.
      const waving = progress(ms, [RUN.peel[0], RUN.carry[0]])
      const wave = waving > 0 && waving < 1 ? Math.sin(waving * Math.PI * 6) * 11 * Math.sin(Math.PI * waving) : 0
      style(ghostEl.querySelector<HTMLElement>(".jc-ghost-wave"), wave ? `rotate(${wave}deg)` : "")
    },
    [measure, stays, style],
  )

  // The run's loop: one frame at a time while it may play; it remembers where it stopped.
  useEffect(() => {
    if (!running) return
    let frame = 0
    let last = performance.now()
    const tick = (now: number) => {
      clockMs.current += Math.min(64, now - last)
      last = now
      if (clockMs.current >= RUN.total) {
        clockMs.current = 0
        restart.current = false
        geometry.current = null
      }
      apply(clockMs.current)
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [running, apply])

  // A new choice: with motion, the ghost goes to fetch the plan again now; paused or without
  // motion, the result simply shows.
  const still = useRef(false)
  still.current = reducedMotion || paused
  const firstChoice = useRef(true)
  useEffect(() => {
    if (firstChoice.current) {
      firstChoice.current = false
      return
    }
    const midRun = clockMs.current < RUN.settle[1]
    clear()
    if (still.current) {
      clockMs.current = FIRST_MS
      return
    }
    restart.current = midRun
    clockMs.current = 0
  }, [mode, clear])

  // Reduced motion, or a resize mid-run: back to the landed state, measured afresh next time.
  useEffect(() => {
    if (reducedMotion) {
      clear()
      clockMs.current = FIRST_MS
    }
  }, [reducedMotion, clear])
  useEffect(() => {
    const onResize = () => {
      geometry.current = null
    }
    window.addEventListener("resize", onResize)
    return () => window.removeEventListener("resize", onResize)
  }, [])

  const hourRows = Array.from({ length: WORK_HOURS.to - WORK_HOURS.from }, (_, index) => WORK_HOURS.from + index)
  const slot = { "--from": DENTIST_TIME.start - WORK_HOURS.from, "--span": DENTIST_TIME.end - DENTIST_TIME.start } as CSSProperties

  return (
    <div ref={root} className="jc" data-hydrated={hydrated ? "true" : "false"} data-playing={running ? "true" : "false"}>
      <div className="jc-controls">
        <fieldset className="jc-group jc-modes">
          <legend>{m.switchLabel}</legend>
          <div className="jc-options jc-segment">
            {MODES.map((option) => (
              <label key={option} className="jc-option jc-mode-option">
                <input type="radio" name="jc-mode" value={option} checked={mode === option} onChange={() => setMode(option)} />
                <span className="jc-option-text">{option === "busy" ? m.busyOnly : m.withDetails}</span>
              </label>
            ))}
          </div>
        </fieldset>
        <div className="jc-toggle">
          <MotionToggle paused={paused} onToggle={() => setPaused((value) => !value)} m={m.motion} compact={compactToggle} />
        </div>
      </div>

      <p className="jc-explain" aria-live="polite">
        <span data-mode="busy">{m.busyOnlyBody}</span>
        <span data-mode="details">{m.withDetailsBody}</span>
      </p>

      <div className="jc-cal jc-from" aria-hidden="true">
        <header className="jc-cal-head">
          <img className="avatar" src={avatars.personal} alt="" width={64} height={64} />
          <b>{m.calendars.personal}</b>
          <span>{m.day}</span>
        </header>
        <div ref={source} className="jc-source">
          <PlanCard plan={plan} when={when} />
        </div>
      </div>

      <svg className="jc-arc" viewBox="0 0 400 200" preserveAspectRatio="none" aria-hidden="true" focusable="false">
        <path d="M8 150C90 20 310 20 392 120" />
      </svg>

      <div className="jc-cal jc-to" aria-hidden="true">
        <header className="jc-cal-head">
          <img className="avatar" src={avatars.work} alt="" width={64} height={64} />
          <b>{m.calendars.work}</b>
          <span>{m.day}</span>
        </header>
        <div className="jc-hours">
          {hourRows.map((hour) => (
            <span key={hour} className="jc-hour">
              {clock(hour)}
            </span>
          ))}
          <div ref={landedSlot} className="jc-landed" style={slot}>
            <div className="cal-event is-busy jc-slot" data-mode="busy">
              <span>{m.busy}</span>
              <small>
                {clock(DENTIST_TIME.start)}–{clock(DENTIST_TIME.end)}
              </small>
            </div>
            <div className="cal-event is-personal jc-slot" data-mode="details">
              <span>{plan.title}</span>
              <small>{plan.place}</small>
              <small>{plan.description}</small>
            </div>
          </div>
        </div>
      </div>

      <div ref={traveler} className="jc-traveler" aria-hidden="true">
        <PlanCard plan={plan} when={when} busy={mode === "busy" ? m.busy : undefined} />
      </div>

      <div ref={ghost} className="jc-ghost" aria-hidden="true">
        <div className="jc-ghost-wave">
          {(["neutral", "happy", "wink", "proud"] as const).map((face) => (
            <Ghost key={face} face={face} look={{ x: -1.3, y: 0.5 }} alive="loop" className={`jc-face jc-face-${face}`} />
          ))}
        </div>
        <SpeechBubble side="right" className="jc-says jc-says-peel">
          {m.peel}
        </SpeechBubble>
        <SpeechBubble side="left" className="jc-says jc-says-land">
          <span data-mode="busy">{m.busySays}</span>
          <span data-mode="details">{m.detailsSays}</span>
        </SpeechBubble>
      </div>

      <p className="sr-only">{m.summary}</p>
    </div>
  )
}
