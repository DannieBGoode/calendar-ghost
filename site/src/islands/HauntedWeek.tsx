import { useRef, useState } from "react"
import { HAUNTED_STILL_MS, hauntedFrame } from "../demo/haunted"
import { eventBox } from "../demo/layout"
import { SAM_WEEK } from "../demo/week"
import type { Messages } from "../i18n"
import { EventCard } from "./EventCard"
import { GhostMark } from "./GhostMark"
import { useAnimationFrame, useOnScreen, usePageVisible, usePointerEyes, useReducedMotion } from "./hooks"
import { shouldAnimate } from "./motion"
import { WeekGrid } from "./WeekGrid"

const FRAME = { heightPx: 360, headerPx: 36, gapPx: 3 }
const WORK = SAM_WEEK.filter((event) => event.kind === "work").map((event) => ({ event, box: eventBox(event, FRAME) }))
const INCOMING = SAM_WEEK.filter((event) => event.kind !== "work").map((event) => ({ event, box: eventBox(event, FRAME) }))
const INCOMING_DAYS = INCOMING.map(({ event }) => event.day)

export function HauntedWeek({ m, summary }: { m: Messages["demo"]; summary: string }) {
  const root = useRef<HTMLDivElement>(null)
  const ghost = useRef<HTMLDivElement>(null)
  const [ms, setMs] = useState(HAUNTED_STILL_MS)
  const reducedMotion = useReducedMotion()
  const onScreen = useOnScreen(root)
  const pageVisible = usePageVisible()
  const eyes = usePointerEyes(ghost, onScreen)
  const animating = shouldAnimate({ onScreen, pageVisible, reducedMotion, held: false })
  useAnimationFrame(setMs, animating)
  const frame = hauntedFrame(animating ? ms : HAUNTED_STILL_MS, INCOMING_DAYS)

  return (
    <figure className="haunt">
      <div ref={root} className="haunt-frame" aria-hidden="true">
        <WeekGrid days={m.days}>
          {WORK.map(({ event, box }) => (
            <EventCard key={event.key} box={box} look="work" title={m.events[event.key].title} detail={m.events[event.key].detail} />
          ))}
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
        <div
          ref={ghost}
          className="haunt-ghost"
          style={{ left: `${frame.ghost.xPct}%`, top: `${frame.ghost.yPct}%`, opacity: frame.ghost.visible ? 1 : 0 }}
        >
          <GhostMark eyes={eyes} />
        </div>
        <span className="haunt-label">{m.workCalendar}</span>
      </div>
      <figcaption className="sr-only">{summary}</figcaption>
    </figure>
  )
}
