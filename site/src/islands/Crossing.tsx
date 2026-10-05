import { useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from "react"
import type { AvatarUrls } from "../avatars"
import { crossingFields, type CrossingMode } from "../demo/crossing"
import type { Messages } from "../i18n"
import { iconMarkup, type IconName } from "../icons"
import { Ghost } from "./Ghost"
import { useOnScreen, usePageVisible, useReducedMotion } from "./hooks"
import { MotionToggle } from "./MotionToggle"

const MODES: readonly CrossingMode[] = ["busy", "details"]
/** Sam's Monday Dentist (demo/week.ts). Clock times are not copy. */
const DENTIST_TIME = "15:00–16:30"
const WORK_HOURS = ["14:00", "15:00", "16:00", "17:00"]
/** Matched by position to `crossing.alwaysStays` (Guests, Organizer, Meeting links, Attachments,
 * Invitations), so each part that never crosses over has its own mark. */
const STAYS_ICONS: readonly IconName[] = ["users", "userRound", "video", "paperclip", "mail"]

/** A Lucide mark inline (an island cannot use the Astro-only Icon component). */
function Mark({ name, className }: { name: IconName; className: string }) {
  return <span className="crossing-mark" dangerouslySetInnerHTML={{ __html: iconMarkup(name, className) }} />
}

/**
 * Where the run takes the ghost and the copy, measured from the page as it is laid out, so the
 * same keyframes work side by side (wide) and stacked (narrow).
 * - `--crossing-copy-x/y`: from the landed slot back to the source card (the copy starts there).
 * - `--crossing-fetch-x/y`: from the ghost's resting place to where it takes the copy.
 * - `--crossing-set-x/y`: from the ghost's resting place to where it sets the copy down.
 */
function measureRun(stage: HTMLElement): CSSProperties {
  // Where each part sits without the run's own transform, so a run restarted midway (a new
  // choice) measures from the resting layout, not from wherever the last run had moved things.
  const box = (selector: string) => {
    const element = stage.querySelector<HTMLElement>(selector)!
    const rect = element.getBoundingClientRect()
    const shift = new DOMMatrixReadOnly(getComputedStyle(element).transform)
    return new DOMRect(rect.x - shift.m41, rect.y - shift.m42, rect.width, rect.height)
  }
  const source = box(".crossing-source")
  const landed = box(".crossing-landed")
  const ghost = box(".crossing-ghost")
  // The ghost holds the copy by its top right corner, its hem over the copy's edge.
  const holdX = (right: number) => right - ghost.width * 0.72 - ghost.left
  const holdY = (top: number) => top - ghost.height * 0.62 - ghost.top
  const px = (value: number) => `${Math.round(value)}px`
  return {
    "--crossing-copy-x": px(source.left - landed.left),
    "--crossing-copy-y": px(source.top - landed.top),
    "--crossing-fetch-x": px(holdX(source.left + landed.width)),
    "--crossing-fetch-y": px(holdY(source.top)),
    "--crossing-set-x": px(holdX(landed.right)),
    "--crossing-set-y": px(holdY(landed.top)),
  } as CSSProperties
}

type Run = "ready" | "running" | "rested"

/**
 * You choose what crosses over: Sam's Dentist on Personal, with every part of it, and Work's
 * afternoon. The ghost fetches a copy, the parts the choice leaves out fall away on the way, and
 * it sets the copy down on Work. The parts that never cross over (CONTEXT.md) stay on the
 * Personal card the whole time, and the switch picks Busy-Only or Details Projection.
 *
 * It runs once when it comes into view, and again on each new choice; then it rests on the
 * landed state. That landed state is also what shows without JavaScript and with reduced motion.
 */
export function Crossing({
  m,
  avatars,
}: {
  m: Pick<Messages, "crossing" | "demo" | "motion">
  /** Sam's portraits, shown beside each calendar's name (see avatars/index.ts). */
  avatars?: AvatarUrls
}) {
  const stage = useRef<HTMLDivElement>(null)
  const [mode, setMode] = useState<CrossingMode>("busy")
  const [paused, setPaused] = useState(false)
  // Unset on the server and in the first client render: the landed state, or (with JavaScript
  // and motion allowed) the run's first frame, from the first paint (demos.css).
  const [run, setRun] = useState<Run | undefined>(undefined)
  const [runId, setRunId] = useState(0)
  const [path, setPath] = useState<CSSProperties>({})
  const reducedMotion = useReducedMotion()
  const onScreen = useOnScreen(stage)
  const pageVisible = usePageVisible()
  const fields = crossingFields(mode)
  const dentist = m.demo.events.dentist
  const started = useRef(false)

  const start = useCallback(() => {
    if (!stage.current) return
    setPath(measureRun(stage.current))
    setRunId((id) => id + 1)
    setRun("running")
  }, [])

  useLayoutEffect(() => {
    // The media query is read directly: the hook reports false until its own effect has run.
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) setRun("rested")
    else setRun("ready")
  }, [])
  useEffect(() => {
    if (reducedMotion) setRun("rested")
  }, [reducedMotion])
  // The first run, once the demo is well in view (so it does not play out below the fold).
  useEffect(() => {
    const element = stage.current
    if (run !== "ready" || !element || started.current) return
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry?.isIntersecting || started.current) return
        started.current = true
        start()
      },
      { threshold: 0.45 },
    )
    observer.observe(element)
    return () => observer.disconnect()
  }, [run, start])

  const choose = (next: CrossingMode) => {
    setMode(next)
    if (next !== mode && !reducedMotion && !paused) {
      started.current = true
      start()
    }
  }

  return (
    <div
      className="crossing"
      data-mode={mode}
      data-run={run}
      data-playing={onScreen && pageVisible && !paused ? "true" : "false"}
    >
      <div className="crossing-bar">
        <div className="crossing-switch" role="group" aria-label={m.crossing.switchLabel}>
          {MODES.map((option) => (
            <button key={option} type="button" aria-pressed={mode === option} onClick={() => choose(option)}>
              {option === "busy" ? m.crossing.busyOnly : m.crossing.withDetails}
            </button>
          ))}
        </div>
        <p className="crossing-explain" aria-live="polite">
          {mode === "busy" ? m.crossing.busyOnlyBody : m.crossing.withDetailsBody}
        </p>
        <MotionToggle compact paused={paused} onToggle={() => setPaused((value) => !value)} m={m.motion} />
      </div>
      <div ref={stage} className="crossing-stage" style={path}>
        <div className="crossing-side crossing-personal">
          <p className="crossing-name" aria-hidden="true">
            {avatars ? <img className="avatar" src={avatars.personal} alt="" width={64} height={64} /> : null}
            {m.demo.calendars.personal}
          </p>
          <div className="crossing-event">
            <div className="crossing-source" aria-hidden="true">
              <span className="crossing-source-title" data-crosses={fields.title}>
                {dentist.title}
              </span>
              <span className="crossing-source-row" data-crosses="true">
                <Mark name="clock" className="crossing-icon" />
                {m.demo.days[0]} {DENTIST_TIME}
              </span>
              <span className="crossing-source-row" data-crosses={fields.location}>
                <Mark name="mapPin" className="crossing-icon" />
                {dentist.detail}
              </span>
            </div>
            <div className="crossing-stays">
              <h3>{m.crossing.alwaysStaysTitle}</h3>
              <ul>
                {m.crossing.alwaysStays.map((item, index) => (
                  <li key={item}>
                    <Mark name={STAYS_ICONS[index] ?? "users"} className="crossing-icon" />
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
        <div className="crossing-side crossing-work" aria-hidden="true">
          <p className="crossing-name">
            {avatars ? <img className="avatar" src={avatars.work} alt="" width={64} height={64} /> : null}
            {m.demo.calendars.work}
          </p>
          <div className="crossing-day">
            {WORK_HOURS.map((hour) => (
              <span key={hour} className="crossing-hour">
                {hour}
              </span>
            ))}
            {/* The landed copy. During a run it starts on the Personal card as a full copy and
                drops what the choice leaves out on its way over. */}
            <div key={`copy-${runId}`} className="crossing-landed">
              <span className="crossing-landed-title" data-crosses={fields.title}>
                {dentist.title}
              </span>
              <span className="crossing-landed-busy" data-crosses={!fields.title}>
                {m.demo.busy}
              </span>
              <span className="crossing-landed-row crossing-landed-time">{DENTIST_TIME}</span>
              <span className="crossing-landed-row crossing-landed-place" data-crosses={fields.location}>
                {dentist.detail}
              </span>
            </div>
          </div>
        </div>
        <span className="crossing-path" aria-hidden="true" />
        <div
          key={`ghost-${runId}`}
          className="crossing-ghost"
          aria-hidden="true"
          onAnimationEnd={(event) => {
            if (event.target === event.currentTarget) setRun("rested")
          }}
        >
          <Ghost face="neutral" then={mode === "busy" ? "happy" : "wink"} alive="loop" />
        </div>
      </div>
      <p className="sr-only">{m.crossing.summary}</p>
    </div>
  )
}
