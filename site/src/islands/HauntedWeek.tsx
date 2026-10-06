import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react"
import type { AvatarUrls } from "../avatars"
import { HAUNTED_STILL_MS, hauntedFrame, phoneCell, PHONE_COLUMNS, pointOnPath, waypoints, type IncomingState } from "../demo/haunted"
import { DAY_END, DAY_START, SAM_WEEK, type DemoEvent } from "../demo/week"
import type { Messages } from "../i18n"
import { Ghost, type GhostTone } from "./Ghost"
import { useAnimationFrame, useOnScreen, usePageVisible, usePointerEyes, useReducedMotion } from "./hooks"
import { shouldAnimate } from "./motion"
import { MotionToggle } from "./MotionToggle"

const WORK = SAM_WEEK.filter((event) => event.kind === "work")
/** What crosses over, in the order the ghost meets it (by day). */
const INCOMING = SAM_WEEK.filter((event) => event.kind !== "work").sort((a, b) => a.day - b.day)
const PATH = { wide: waypoints(INCOMING, "wide"), phone: waypoints(INCOMING, "phone") }
const HOURS = Array.from({ length: DAY_END - DAY_START }, (_, index) => DAY_START + index)
/** On phones an event shorter than this many hours has room for one line only (demos.css). */
const PHONE_TWO_LINES_HOURS = 1.5

/** Where an event sits: its day and hours (wide), and its column and row (phone); demos.css
 * turns these into places, so both layouts come from the same markup. */
function place(event: DemoEvent): CSSProperties {
  const cell = phoneCell(event.day)
  return {
    "--day": event.day,
    "--col-p": cell.col,
    "--row-p": cell.row,
    "--start": event.start - DAY_START,
    "--len": event.end - event.start,
  } as CSSProperties
}

/** The hour labels and the days of one row of the week. */
function WeekRow({ days, columns, layout, row = 0 }: { days: readonly string[]; columns: number; layout: "wide" | "phone"; row?: number }) {
  return (
    <div className={`hw-row is-${layout}`} style={{ "--row": row } as CSSProperties}>
      <span className="hw-corner" />
      {Array.from({ length: columns }, (_, index) => (
        <span key={`day-${index}`} className={days[index] ? "hw-day" : "hw-day is-empty"} style={{ gridColumn: index + 2 }}>
          {days[index]}
        </span>
      ))}
      <span className="hw-hours">
        {HOURS.map((hour, index) => (
          <span key={hour} style={{ "--hour-i": index } as CSSProperties}>
            {layout === "wide" ? `${String(hour).padStart(2, "0")}:00` : hour}
          </span>
        ))}
      </span>
      {days.map((day, index) => (
        <span key={`col-${day}`} className="hw-col" style={{ gridColumn: index + 2 }} />
      ))}
    </div>
  )
}

/** The small ghost that marks a Busy block (the mark's silhouette, with its eyes). */
function BusyGlyph() {
  return (
    <svg className="hw-glyph" viewBox="5 3 22 23" aria-hidden="true" focusable="false">
      <path d="M6 13a6 6 0 0 1 6-6h8a6 6 0 0 1 6 6v11q-2 3-4 0q-2-3-4 0q-2 3-4 0q-2-3-4 0q-2 3-4 0Z" />
      <path className="hw-glyph-tab" d="M12 4.5v4M20 4.5v4" />
      <circle className="hw-glyph-eye" cx="13" cy="15" r="1.9" />
      <circle className="hw-glyph-eye" cx="19" cy="15" r="1.9" />
    </svg>
  )
}

export function HauntedWeek({
  m,
  motion,
  summary,
  ghostTone = "mist",
  avatars,
}: {
  m: Messages["demo"]
  motion: Messages["motion"]
  summary: string
  /** The roaming ghost's tone (default mist: the white glowing ghost on dark, Lantern Indigo on
   * light). */
  ghostTone?: GhostTone
  /** Sam's portraits: the Work one names the calendar, and each incoming plan carries its own
   * calendar's (see avatars/index.ts). */
  avatars?: AvatarUrls
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
  const frame = hauntedFrame(reducedMotion ? HAUNTED_STILL_MS : ms, INCOMING.length)
  // Watching on the way in; delighted once the first plan has turned into Busy.
  const face = frame.incoming[0] === "busy" ? "happy" : "neutral"
  const wide = pointOnPath(PATH.wide, frame.run ?? 0)
  const phone = pointOnPath(PATH.phone, frame.run ?? 0)

  // The week itself and Work's own meetings never change, so a frame of the loop re-renders only
  // what crosses over and the ghost.
  const week = useMemo(
    () => (
      <>
        <WeekRow days={m.days} columns={m.days.length} layout="wide" />
        <WeekRow days={m.days.slice(0, PHONE_COLUMNS)} columns={PHONE_COLUMNS} layout="phone" />
        <WeekRow days={m.days.slice(PHONE_COLUMNS)} columns={PHONE_COLUMNS} layout="phone" row={1} />
        {WORK.map((event) => (
          <div
            key={event.key}
            className="hw-event is-work"
            style={place(event)}
            data-short-phone={event.end - event.start < PHONE_TWO_LINES_HOURS ? "" : undefined}
          >
            <span className="hw-face">
              <span className="hw-title">{m.events[event.key].title}</span>
              <span className="hw-detail">{m.events[event.key].detail}</span>
            </span>
          </div>
        ))}
      </>
    ),
    [m],
  )

  return (
    <figure className="haunt">
      <div ref={root} className="haunt-frame" data-playing={paused ? "false" : "true"}>
        <div className="haunt-bar">
          <span className="haunt-label" aria-hidden="true">
            {avatars ? <img className="avatar" src={avatars.work} alt="" width={64} height={64} /> : null}
            <span>{m.workCalendar}</span>
          </span>
          <MotionToggle paused={paused} onToggle={() => setPaused((value) => !value)} m={motion} short />
        </div>
        <div className="haunt-week" aria-hidden="true" style={{ "--hours": DAY_END - DAY_START } as CSSProperties}>
          {week}
          {INCOMING.map((event, index) => {
            const source = event.kind === "family" ? "family" : "personal"
            const state: IncomingState = frame.incoming[index] ?? "busy"
            return (
              <div
                key={event.key}
                className="hw-event is-incoming"
                style={place(event)}
                data-source={source}
                data-state={state}
                data-fading={frame.fading ? "" : undefined}
              >
                <span className="hw-skin is-transit" />
                <span className="hw-skin is-busy" />
                <span className="hw-face is-transit">
                  {avatars ? <img className="avatar hw-avatar" src={avatars[source]} alt="" width={64} height={64} /> : null}
                  <span className="hw-title">{m.events[event.key].title}</span>
                </span>
                <span className="hw-face is-busy">
                  <BusyGlyph />
                  <span className="hw-title">{m.busy}</span>
                  <span className="hw-dot" />
                </span>
              </div>
            )
          })}
          {/* The track spans the week, so the ghost moves by a share of its width with transform
              alone; the point it moves is the ghost's hem, which brushes each event's top edge. */}
          <div
            className="haunt-track"
            style={
              {
                "--gx-w": wide.x.toFixed(3),
                "--gy-w": wide.y.toFixed(3),
                "--gx-p": phone.x.toFixed(3),
                "--grow-p": phone.row.toFixed(3),
                "--gy-p": phone.y.toFixed(3),
              } as CSSProperties
            }
          >
            <div ref={ghost} className="haunt-ghost" style={{ opacity: frame.run === null ? 0 : 1 }}>
              <Ghost face={face} tone={ghostTone} look={eyes} alive="loop" size={76} />
            </div>
          </div>
        </div>
      </div>
      <figcaption className="sr-only">{summary}</figcaption>
    </figure>
  )
}
