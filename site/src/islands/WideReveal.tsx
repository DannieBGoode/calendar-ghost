import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react"
import { eventBox } from "../demo/layout"
import { SAM_WEEK } from "../demo/week"
import type { Messages } from "../i18n"
import { format } from "../i18n/format"
import { EventCard } from "./EventCard"
import { Ghost, SpeechBubble, type GhostFace, type GhostTone } from "./Ghost"
import { useAnimationFrame, useOnScreen, usePageVisible, usePointerEyes, useReducedMotion } from "./hooks"
import { MotionToggle } from "./MotionToggle"
import { REVEAL_REST, SWEEP_PERIOD_MS, clampPercent, shouldAnimate, sweepPercent, sweepTimeFor, type SweepShape } from "./motion"
import { WeekGrid } from "./WeekGrid"

const FRAME = { heightPx: 380, headerPx: 36, gapPx: 3 }
const HANDLE_PX = 104

/** Sam's week laid out in a week `heightPx` tall. */
function placeWeek(heightPx: number) {
  return SAM_WEEK.map((event) => ({ event, box: eventBox(event, { ...FRAME, heightPx }) }))
}
const PLACED = placeWeek(FRAME.heightPx)

/** Two decimals is enough to smooth the sweep; trimmed so whole percentages render without them. */
function splitStyle(percent: number): string {
  return `${Math.round(percent * 100) / 100}%`
}

/** How long the ghost looks startled when a visitor takes hold of it, before it enjoys the ride. */
const STARTLE_MS = 450

/** The handle's face: watching while it sweeps, startled when grabbed, then happy to be dragged. */
function useHandleFace(held: boolean): GhostFace {
  const [startled, setStartled] = useState(false)
  useEffect(() => {
    if (!held) return
    setStartled(true)
    const timer = window.setTimeout(() => setStartled(false), STARTLE_MS)
    return () => window.clearTimeout(timer)
  }, [held])
  if (!held) return "neutral"
  return startled ? "surprised" : "happy"
}

export interface WideRevealProps {
  m: Messages["demo"]
  motion: Messages["motion"]
  /** The week's height in pixels, without its day header (default 380). */
  weekHeight?: number
  /** The week's height on phones (under 640px wide), if it differs. */
  phoneWeekHeight?: number
  /** The ghost handle's size in pixels (default 104). */
  handleSize?: number
  /** The ghost handle's size on phones, if it differs. */
  phoneHandleSize?: number
  /** What the ghost says while a visitor holds it, if anything. */
  heldSays?: string
  /** The handle's tone. The default stays moss, so the home hero keeps its ghost until its own
   * redesign; other pages pass the default character, mist. */
  ghostTone?: GhostTone
  /**
   * Where the split rests before it sweeps, and without JavaScript (`rest`, in percent, default
   * 55); which way it heads first (`direction`, default right); and how far it swings each way
   * from the middle (`swing`, default 38 points).
   */
  sweep?: { rest?: number } & Omit<SweepShape, "periodMs">
  /**
   * Where the two views' labels go.
   * - `corners` (default): in the frame's bottom corners, with the hint and the pause control
   *   under the frame.
   * - `divider`: pinned to the divider, so they travel with it; the hint sits under the ghost
   *   handle and the pause control is an icon button in the frame's top-right corner.
   */
  labels?: "corners" | "divider"
  /** With `labels="divider"`, the hint under the handle: one for a mouse, one for touch. */
  handleHint?: { mouse: string; touch: string }
}

/** The hero: Sam's week as Sam sees it, revealed over what work sees, with the ghost as handle. */
export function WideReveal({
  m,
  motion,
  weekHeight = FRAME.heightPx,
  phoneWeekHeight,
  handleSize = HANDLE_PX,
  phoneHandleSize,
  heldSays,
  ghostTone = "moss",
  sweep = {},
  labels = "corners",
  handleHint,
}: WideRevealProps) {
  const pinned = labels === "divider"
  const { rest = REVEAL_REST, direction, swing } = sweep
  const placed = useMemo(() => (weekHeight === FRAME.heightPx ? PLACED : placeWeek(weekHeight)), [weekHeight])
  // Each event's place on phones, by index, when the week there has its own height.
  const phonePlaced = useMemo(() => (phoneWeekHeight ? placeWeek(phoneWeekHeight) : null), [phoneWeekHeight])
  const frame = useRef<HTMLDivElement>(null)
  const handle = useRef<HTMLDivElement>(null)
  const [held, setHeld] = useState<number | null>(null)
  const [auto, setAuto] = useState(rest)
  const [phase, setPhase] = useState(() => sweepTimeFor(rest, { direction, swing }))
  const [paused, setPaused] = useState(false)
  const reducedMotion = useReducedMotion()
  const onScreen = useOnScreen(frame)
  const pageVisible = usePageVisible()
  const eyes = usePointerEyes(handle, onScreen)
  const animating = shouldAnimate({ onScreen, pageVisible, reducedMotion, held: held !== null || paused })
  const face = useHandleFace(held !== null)
  useAnimationFrame((elapsed) => setAuto(sweepPercent(phase + elapsed, SWEEP_PERIOD_MS, swing)), animating)

  // When the loop stops (scrolled away, tab hidden, reduced motion), remember the phase at the
  // point it stopped, so the next run resumes from there instead of jumping back to center.
  const wasAnimating = useRef(animating)
  useEffect(() => {
    if (wasAnimating.current && !animating) setPhase(sweepTimeFor(auto, { direction, swing }))
    wasAnimating.current = animating
  }, [animating, auto, direction, swing])

  const splitValue = held ?? auto
  const split = Math.round(splitValue)
  const release = () => {
    if (held === null) return
    setPhase(sweepTimeFor(held, { direction, swing }))
    setAuto(held)
    setHeld(null)
  }

  // These two layers never depend on `split`, so memoizing them keeps a sweep frame to updating
  // only the CSS variable, the range input, and the handle.
  const workLayer = useMemo(
    () => (
      <div className="reveal-layer reveal-work" aria-hidden="true">
        <WeekGrid days={m.days} className="reveal-week">
          {placed.map(({ event, box }, index) =>
            event.kind === "work" ? (
              <EventCard
                key={event.key}
                box={box}
                phoneBox={phonePlaced?.[index]?.box}
                look="work"
                title={m.events[event.key].title}
                detail={m.events[event.key].detail}
              />
            ) : (
              <EventCard key={event.key} box={box} phoneBox={phonePlaced?.[index]?.box} look="busy" title={m.busy} />
            ),
          )}
        </WeekGrid>
        {pinned ? null : <span className="reveal-tag reveal-tag-work">{m.workSees}</span>}
      </div>
    ),
    [m, placed, phonePlaced, pinned],
  )
  const youLayer = useMemo(
    () => (
      <div className="reveal-layer reveal-you" aria-hidden="true">
        <WeekGrid days={m.days} className="reveal-week">
          {placed.map(({ event, box }, index) => (
            <EventCard
              key={event.key}
              box={box}
              phoneBox={phonePlaced?.[index]?.box}
              look={event.kind}
              title={m.events[event.key].title}
              detail={m.events[event.key].detail}
            />
          ))}
        </WeekGrid>
        {pinned ? null : <span className="reveal-tag reveal-tag-you">{m.youSee}</span>}
      </div>
    ),
    [m, placed, phonePlaced, pinned],
  )
  // Only a non-default size is written, so the default page renders exactly as before.
  const sizing: Record<string, string> = {}
  if (weekHeight !== FRAME.heightPx) sizing["--reveal-week-h"] = `${weekHeight}px`
  if (handleSize !== HANDLE_PX) sizing["--handle-size"] = `${handleSize}px`
  if (phoneWeekHeight) sizing["--reveal-week-h-phone"] = `${phoneWeekHeight}px`
  if (phoneHandleSize) sizing["--handle-size-phone"] = `${phoneHandleSize}px`
  const toggle = <MotionToggle paused={paused} onToggle={() => setPaused((value) => !value)} m={motion} compact={pinned} />

  return (
    <figure className="reveal">
      <div
        ref={frame}
        className="reveal-frame"
        data-playing={paused ? "false" : "true"}
        data-labels={pinned ? "divider" : undefined}
        data-held={pinned && held !== null ? "" : undefined}
        style={{ ...sizing, "--split": splitStyle(splitValue) } as CSSProperties}
      >
        {workLayer}
        {youLayer}
        {/* Both rails span the frame and slide by --split, so the sweep moves them with
            transform alone. */}
        <div className="reveal-rail" aria-hidden="true">
          <div className="reveal-divider" />
        </div>
        {pinned ? (
          <div className="reveal-rail reveal-pins" aria-hidden="true">
            <span className="reveal-pin reveal-pin-you">{m.youSee}</span>
            <span className="reveal-pin reveal-pin-work">{m.workSees}</span>
          </div>
        ) : null}
        <div className="reveal-rail" aria-hidden="true">
          <div ref={handle} className="reveal-handle" data-face={face}>
            <Ghost face={face} tone={ghostTone} look={eyes} alive="loop" className="reveal-ghost" />
            {heldSays && held !== null ? (
              <SpeechBubble side="top" className="reveal-says">
                {heldSays}
              </SpeechBubble>
            ) : null}
            {pinned && handleHint ? (
              <span className="reveal-handle-hint">
                <span className="reveal-hint-mouse">{handleHint.mouse}</span>
                <span className="reveal-hint-touch">{handleHint.touch}</span>
              </span>
            ) : null}
          </div>
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
          onFocus={() => setHeld(split)}
          onPointerMove={(event) => {
            if (event.pointerType !== "mouse" || event.buttons !== 0) return
            const box = event.currentTarget.getBoundingClientRect()
            setHeld(clampPercent(((event.clientX - box.left) / box.width) * 100))
          }}
          onPointerLeave={release}
          onBlur={release}
        />
        {pinned ? toggle : null}
      </div>
      <figcaption className="sr-only">{m.revealSummary}</figcaption>
      {pinned ? null : (
        <div className="demo-foot">
          <p className="reveal-hint" aria-hidden="true">
            {m.hint}
          </p>
          {toggle}
        </div>
      )}
    </figure>
  )
}
