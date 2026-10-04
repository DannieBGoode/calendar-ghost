import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react"
import { eventBox } from "../../demo/layout"
import { SAM_WEEK } from "../../demo/week"
import type { Messages } from "../../i18n"
import { format } from "../../i18n/format"
import { EventCard } from "../../islands/EventCard"
import { Ghost, type GhostFace } from "../../islands/Ghost"
import { useAnimationFrame, useHydrated, useOnScreen, usePageVisible, usePointerEyes, useReducedMotion } from "../../islands/hooks"
import { MotionToggle } from "../../islands/MotionToggle"
import { REVEAL_REST, clampPercent, shouldAnimate, sweepPercent, sweepTimeFor } from "../../islands/motion"
import { WeekGrid } from "../../islands/WeekGrid"
import { INTRO_FROM, INTRO_MS, hasArrived, introSplit } from "./week-intro"

const HEADER_PX = 36
const GAP_PX = 3
const STARTLE_MS = 450

function placeWeek(heightPx: number) {
  return SAM_WEEK.map((event) => ({ event, box: eventBox(event, { heightPx, headerPx: HEADER_PX, gapPx: GAP_PX }) }))
}

/** Sam's plans carry a class with their name, so the page can point out the one picked above. */
function planClass(key: string): string {
  return `je-plan je-plan-${key}`
}

/** Watching while it sweeps, startled when grabbed, then happy to be dragged. */
function useHandleFace(held: boolean, working: boolean): GhostFace {
  const [startled, setStartled] = useState(false)
  useEffect(() => {
    if (!held) return
    setStartled(true)
    const timer = window.setTimeout(() => setStartled(false), STARTLE_MS)
    return () => window.clearTimeout(timer)
  }, [held])
  if (held) return startled ? "surprised" : "happy"
  return working ? "proud" : "neutral"
}

/** True once at least `threshold` of the element has been in view. */
function useSeen(ref: React.RefObject<Element | null>, threshold: number): boolean {
  const [seen, setSeen] = useState(false)
  useEffect(() => {
    const element = ref.current
    if (!element || seen) return
    const observer = new IntersectionObserver(([entry]) => {
      if (entry?.isIntersecting) setSeen(true)
    }, { threshold })
    observer.observe(element)
    return () => observer.disconnect()
  }, [ref, threshold, seen])
  return seen
}

/**
 * The whole week on /journey: the Wide Reveal with the Haunted Week's idea folded in. Forked from
 * islands/WideReveal.tsx because it opens differently: the first time it is well in view, the
 * ghost (the divider) sweeps from right to left and Sam's plans arrive on work's side as Busy as it
 * passes; then it settles at rest and sweeps gently, like the home page's hero, until a visitor
 * takes hold of it. Without JavaScript or with reduced motion it simply rests, every plan in place.
 */
export function JourneyReveal({
  m,
  motion,
  weekHeight,
  phoneWeekHeight,
  handleSize,
  phoneHandleSize,
}: {
  m: Messages["demo"]
  motion: Messages["motion"]
  weekHeight: number
  phoneWeekHeight: number
  handleSize: number
  phoneHandleSize: number
}) {
  const placed = useMemo(() => placeWeek(weekHeight), [weekHeight])
  const phonePlaced = useMemo(() => placeWeek(phoneWeekHeight), [phoneWeekHeight])
  const frame = useRef<HTMLDivElement>(null)
  const handle = useRef<HTMLDivElement>(null)
  const [held, setHeld] = useState<number | null>(null)
  const [auto, setAuto] = useState(REVEAL_REST)
  const [phase, setPhase] = useState(() => sweepTimeFor(REVEAL_REST))
  const [paused, setPaused] = useState(false)
  // The opening pass: waiting until it is well in view, then running, then done for good.
  const [introMs, setIntroMs] = useState(0)
  const [introDone, setIntroDone] = useState(false)
  const introStart = useRef(0)
  const hydrated = useHydrated()
  const reducedMotion = useReducedMotion()
  const onScreen = useOnScreen(frame)
  const seen = useSeen(frame, 0.45)
  const pageVisible = usePageVisible()
  const eyes = usePointerEyes(handle, onScreen)
  const intro = hydrated && !reducedMotion && !introDone
  const introRunning = intro && seen && onScreen && pageVisible && !paused && held === null
  const animating = !intro && shouldAnimate({ onScreen, pageVisible, reducedMotion, held: held !== null || paused })
  const face = useHandleFace(held !== null, intro && introMs > 0)

  useAnimationFrame((elapsed) => {
    const ms = introStart.current + elapsed
    if (ms >= INTRO_MS) {
      setIntroDone(true)
      setIntroMs(INTRO_MS)
      return
    }
    setIntroMs(ms)
  }, introRunning)
  // A pass that stops (paused, scrolled away) resumes where it was.
  const wasRunning = useRef(introRunning)
  useEffect(() => {
    if (wasRunning.current && !introRunning) introStart.current = introMs
    wasRunning.current = introRunning
  }, [introRunning, introMs])
  // Taking hold of the ghost mid-pass ends the pass: everything arrives at once.
  useEffect(() => {
    if (held !== null && intro) setIntroDone(true)
  }, [held, intro])

  useAnimationFrame((elapsed) => setAuto(sweepPercent(phase + elapsed)), animating)
  const wasAnimating = useRef(animating)
  useEffect(() => {
    if (wasAnimating.current && !animating) setPhase(sweepTimeFor(auto))
    wasAnimating.current = animating
  }, [animating, auto])

  const splitValue = held ?? (intro ? introSplit(introMs) : auto)
  const split = Math.round(splitValue)
  const release = () => {
    if (held === null) return
    setPhase(sweepTimeFor(held))
    setAuto(held)
    setHeld(null)
  }

  const youLayer = useMemo(
    () => (
      <div className="reveal-layer reveal-you" aria-hidden="true">
        <WeekGrid days={m.days} className="reveal-week">
          {placed.map(({ event, box }, index) => (
            <EventCard
              key={event.key}
              box={box}
              phoneBox={phonePlaced[index]?.box}
              look={event.kind}
              title={m.events[event.key].title}
              detail={m.events[event.key].detail}
              className={event.kind === "work" ? "" : planClass(event.key)}
            />
          ))}
        </WeekGrid>
        <span className="reveal-tag reveal-tag-you">{m.youSee}</span>
      </div>
    ),
    [m, placed, phonePlaced],
  )

  // Work's side. During the opening pass each plan waits, hidden, until the ghost has passed it.
  const workLayer = (
    <div className="reveal-layer reveal-work" aria-hidden="true">
      <WeekGrid days={m.days} className="reveal-week">
        {placed.map(({ event, box }, index) => {
          if (event.kind === "work") {
            return (
              <EventCard
                key={event.key}
                box={box}
                phoneBox={phonePlaced[index]?.box}
                look="work"
                title={m.events[event.key].title}
                detail={m.events[event.key].detail}
              />
            )
          }
          const waiting = intro && !hasArrived(box, introMs > 0 ? splitValue : INTRO_FROM)
          const state = waiting ? "is-waiting" : intro ? "is-settled" : ""
          return (
            <EventCard
              key={event.key}
              box={box}
              phoneBox={phonePlaced[index]?.box}
              look="busy"
              title={m.busy}
              className={`${planClass(event.key)} ${state}`.trim()}
            />
          )
        })}
      </WeekGrid>
      <span className="reveal-tag reveal-tag-work">{m.workSees}</span>
    </div>
  )

  const sizing = {
    "--reveal-week-h": `${weekHeight}px`,
    "--handle-size": `${handleSize}px`,
    "--reveal-week-h-phone": `${phoneWeekHeight}px`,
    "--handle-size-phone": `${phoneHandleSize}px`,
  }

  return (
    <figure className="reveal jr">
      <div
        ref={frame}
        className="reveal-frame"
        data-playing={paused ? "false" : "true"}
        style={{ ...sizing, "--split": `${Math.round(splitValue * 100) / 100}%` } as CSSProperties}
      >
        {workLayer}
        {youLayer}
        <div className="reveal-rail" aria-hidden="true">
          <div className="reveal-divider" />
        </div>
        <div className="reveal-rail" aria-hidden="true">
          <div ref={handle} className="reveal-handle" data-face={face}>
            <Ghost face={face} look={eyes} alive="loop" className="reveal-ghost" />
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
      </div>
      <figcaption className="sr-only">{m.revealSummary}</figcaption>
      <div className="demo-foot">
        <p className="reveal-hint" aria-hidden="true">
          {m.hint}
        </p>
        <MotionToggle paused={paused} onToggle={() => setPaused((value) => !value)} m={motion} />
      </div>
    </figure>
  )
}
