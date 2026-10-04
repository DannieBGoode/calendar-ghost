import { useRef, useState, type CSSProperties } from "react"
import { eventBox } from "../demo/layout"
import { SAM_WEEK } from "../demo/week"
import type { Messages } from "../i18n"
import { format } from "../i18n/format"
import { EventCard } from "./EventCard"
import { GhostMark } from "./GhostMark"
import { useAnimationFrame, useOnScreen, usePageVisible, usePointerEyes, useReducedMotion } from "./hooks"
import { REVEAL_REST, clampPercent, shouldAnimate, sweepPercent, sweepTimeFor } from "./motion"
import { WeekGrid } from "./WeekGrid"

const FRAME = { heightPx: 380, headerPx: 36, gapPx: 3 }
const PLACED = SAM_WEEK.map((event) => ({ event, box: eventBox(event, FRAME) }))

/** The hero: Sam's week as Sam sees it, revealed over what work sees, with the ghost as handle. */
export function WideReveal({ m }: { m: Messages["demo"] }) {
  const frame = useRef<HTMLDivElement>(null)
  const handle = useRef<HTMLDivElement>(null)
  const [held, setHeld] = useState<number | null>(null)
  const [auto, setAuto] = useState(REVEAL_REST)
  const [phase, setPhase] = useState(() => sweepTimeFor(REVEAL_REST))
  const reducedMotion = useReducedMotion()
  const onScreen = useOnScreen(frame)
  const pageVisible = usePageVisible()
  const eyes = usePointerEyes(handle)
  const animating = shouldAnimate({ onScreen, pageVisible, reducedMotion, held: held !== null })
  useAnimationFrame((elapsed) => setAuto(sweepPercent(phase + elapsed)), animating)

  const split = Math.round(held ?? auto)
  const release = () => {
    if (held === null) return
    setPhase(sweepTimeFor(held))
    setAuto(held)
    setHeld(null)
  }

  return (
    <figure className="reveal">
      <div ref={frame} className="reveal-frame" style={{ "--split": `${split}%` } as CSSProperties}>
        <div className="reveal-layer reveal-work">
          <WeekGrid days={m.days} className="reveal-week">
            {PLACED.map(({ event, box }) =>
              event.kind === "work" ? (
                <EventCard key={event.key} box={box} look="work" title={m.events[event.key].title} detail={m.events[event.key].detail} />
              ) : (
                <EventCard key={event.key} box={box} look="busy" title={m.busy} />
              ),
            )}
          </WeekGrid>
          <span className="reveal-tag reveal-tag-work">{m.workSees}</span>
        </div>
        <div className="reveal-layer reveal-you">
          <WeekGrid days={m.days} className="reveal-week">
            {PLACED.map(({ event, box }) => (
              <EventCard key={event.key} box={box} look={event.kind} title={m.events[event.key].title} detail={m.events[event.key].detail} />
            ))}
          </WeekGrid>
          <span className="reveal-tag reveal-tag-you">{m.youSee}</span>
        </div>
        <div className="reveal-divider" aria-hidden="true" />
        <div ref={handle} className="reveal-handle" aria-hidden="true">
          <GhostMark className="ghost-bob" eyes={eyes} />
        </div>
        <input
          className="reveal-range"
          type="range"
          min={2}
          max={98}
          step={1}
          value={split}
          aria-label={m.sliderLabel}
          aria-valuetext={format(m.sliderValueText, { percent: split })}
          onChange={(event) => setHeld(clampPercent(Number(event.currentTarget.value)))}
          onPointerMove={(event) => {
            if (event.pointerType !== "mouse" || event.buttons !== 0) return
            const box = event.currentTarget.getBoundingClientRect()
            setHeld(clampPercent(((event.clientX - box.left) / box.width) * 100))
          }}
          onPointerLeave={release}
          onBlur={release}
        />
      </div>
      <figcaption className="sr-only">{m.revealSummary}</figcaption>
      <p className="reveal-hint" aria-hidden="true">
        {m.hint}
      </p>
    </figure>
  )
}
