import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react"
import { HAUNTED_STILL_MS, hauntedFrame } from "../demo/haunted"
import { eventBox } from "../demo/layout"
import { SAM_WEEK } from "../demo/week"
import type { Messages } from "../i18n"
import { EventCard } from "./EventCard"
import { Ghost, type GhostTone } from "./Ghost"
import { useAnimationFrame, useOnScreen, usePageVisible, usePointerEyes, useReducedMotion } from "./hooks"
import { shouldAnimate } from "./motion"
import { MotionToggle } from "./MotionToggle"
import { WeekGrid } from "./WeekGrid"

const FRAME = { heightPx: 360, headerPx: 36, gapPx: 3 }
const WORK = SAM_WEEK.filter((event) => event.kind === "work").map((event) => ({ event, box: eventBox(event, FRAME) }))
const INCOMING = SAM_WEEK.filter((event) => event.kind !== "work").map((event) => ({ event, box: eventBox(event, FRAME) }))
const INCOMING_DAYS = INCOMING.map(({ event }) => event.day)

export function HauntedWeek({
  m,
  motion,
  summary,
  ghostTone = "moss",
}: {
  m: Messages["demo"]
  motion: Messages["motion"]
  summary: string
  /** The roaming ghost's tone (default moss, the healthy green). */
  ghostTone?: GhostTone
}) {
  const root = useRef<HTMLDivElement>(null)
  const ghost = useRef<HTMLDivElement>(null)
  const [ms, setMs] = useState(HAUNTED_STILL_MS)
  const [paused, setPaused] = useState(false)
  // Where the loop resumes after it stops (paused, scrolled away, tab hidden). The first run
  // starts from the beginning; until then the still frame shows.
  const resumeAt = useRef(0)
  const reducedMotion = useReducedMotion()
  const onScreen = useOnScreen(root)
  const pageVisible = usePageVisible()
  const eyes = usePointerEyes(ghost, onScreen)
  const animating = shouldAnimate({ onScreen, pageVisible, reducedMotion, held: paused })
  useAnimationFrame((elapsed) => setMs(resumeAt.current + elapsed), animating)
  const wasAnimating = useRef(animating)
  useEffect(() => {
    if (wasAnimating.current && !animating) resumeAt.current = ms
    wasAnimating.current = animating
  }, [animating, ms])
  const frame = hauntedFrame(reducedMotion ? HAUNTED_STILL_MS : ms, INCOMING_DAYS)
  // Watching on the way in; delighted once the first plan has turned into Busy.
  const face = frame.busy.some(Boolean) ? "happy" : "neutral"

  // Work's own meetings never change, so a frame of the loop re-renders only what crosses over.
  const workEvents = useMemo(
    () =>
      WORK.map(({ event, box }) => (
        <EventCard key={event.key} box={box} look="work" title={m.events[event.key].title} detail={m.events[event.key].detail} />
      )),
    [m],
  )

  return (
    <figure className="haunt">
      <div ref={root} className="haunt-frame" data-playing={paused ? "false" : "true"} aria-hidden="true">
        <WeekGrid days={m.days}>
          {workEvents}
          {INCOMING.map(({ event, box }, index) => {
            const busy = frame.busy[index]
            const state = [frame.shown[index] ? "is-shown" : "is-arriving", busy ? "is-settled" : "", frame.fading ? "is-fading" : ""]
            return (
              <EventCard
                key={event.key}
                box={box}
                look={busy ? "busy" : event.kind}
                title={busy ? m.busy : m.events[event.key].title}
                detail={busy ? undefined : m.from[event.kind === "family" ? "family" : "personal"]}
                className={state.filter(Boolean).join(" ")}
              />
            )
          })}
        </WeekGrid>
        {/* The track spans the frame, so the ghost moves by a percentage of the frame with
            transform alone. */}
        <div
          className="haunt-track"
          style={{ "--haunt-x": `${frame.ghost.xPct}%`, "--haunt-y": `${frame.ghost.yPct}%` } as CSSProperties}
        >
          <div ref={ghost} className="haunt-ghost" style={{ opacity: frame.ghost.visible ? 1 : 0 }}>
            <Ghost face={face} tone={ghostTone} look={eyes} alive="loop" size={84} />
          </div>
        </div>
        <span className="haunt-label">{m.workCalendar}</span>
      </div>
      <figcaption className="sr-only">{summary}</figcaption>
      <div className="demo-foot">
        <MotionToggle paused={paused} onToggle={() => setPaused((value) => !value)} m={motion} />
      </div>
    </figure>
  )
}
