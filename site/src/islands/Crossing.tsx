import { useRef, useState } from "react"
import { crossingFields, type CrossingMode } from "../demo/crossing"
import type { Messages } from "../i18n"
import { Ghost, SpeechBubble } from "./Ghost"
import { useHydrated, useOnScreen, usePageVisible } from "./hooks"
import { MotionToggle } from "./MotionToggle"

const HOURS = ["14:00", "15:00", "16:00", "17:00"]
const MODES: readonly CrossingMode[] = ["busy", "details"]

function fieldClass(stays: boolean): string {
  return stays ? "crossing-field" : "crossing-field crossing-fades"
}

/** One event carried by the ghost from Personal to Work; the switch picks what crosses over. */
export function Crossing({ m }: { m: Pick<Messages, "crossing" | "demo" | "ghost" | "motion"> }) {
  const stage = useRef<HTMLDivElement>(null)
  const [mode, setMode] = useState<CrossingMode>("busy")
  const [paused, setPaused] = useState(false)
  // Without JavaScript (or before hydration), the loop is paused at its 0% frame, where the
  // traveler is invisible. Show the landed state until the island has taken over.
  const hydrated = useHydrated()
  const onScreen = useOnScreen(stage)
  const pageVisible = usePageVisible()
  const fields = crossingFields(mode)
  const dentist = m.demo.events.dentist

  return (
    <div
      className="crossing"
      data-mode={mode}
      data-playing={onScreen && pageVisible && !paused ? "true" : "false"}
      data-hydrated={hydrated ? "true" : "false"}
    >
      <div className="crossing-controls">
        <div className="crossing-switch" role="group" aria-label={m.crossing.switchLabel}>
          {MODES.map((option) => (
            <button key={option} type="button" aria-pressed={mode === option} onClick={() => setMode(option)}>
              {option === "busy" ? m.crossing.busyOnly : m.crossing.withDetails}
            </button>
          ))}
        </div>
        <p className="crossing-explain" aria-live="polite">
          {mode === "busy" ? m.crossing.busyOnlyBody : m.crossing.withDetailsBody}
        </p>
      </div>
      <div ref={stage} className="crossing-stage" aria-hidden="true">
        {(["personal", "work"] as const).map((calendar) => (
          <div key={calendar} className={`crossing-cal crossing-${calendar}`}>
            <header>{m.demo.calendars[calendar]}</header>
            {HOURS.map((hour) => (
              <div key={hour} className="crossing-row">
                {hour}
              </div>
            ))}
            {calendar === "personal" ? (
              <div className="cal-event is-personal crossing-original">
                <span>{dentist.title}</span>
              </div>
            ) : (
              <div className="cal-event is-work crossing-existing">
                <span>{m.demo.events.clientCall.title}</span>
              </div>
            )}
          </div>
        ))}
        <div key={mode} className="crossing-traveler">
          <div className="cal-event crossing-card">
            <span className={fieldClass(fields.title)}>{dentist.title}</span>
            {fields.title ? null : <span className="crossing-busy">{m.demo.busy}</span>}
            <span className="crossing-chips">
              <small className={fieldClass(fields.location)}>{dentist.detail}</small>
              <small className={fieldClass(fields.guests)}>{m.crossing.guests}</small>
              <small className={fieldClass(fields.link)}>{m.crossing.link}</small>
            </span>
          </div>
          {/* Proud while it carries the event; on landing, happy with Busy only and a wink with
              details. */}
          <div className="crossing-carrier ghost-stage">
            <Ghost face="proud" then={mode === "busy" ? "happy" : "wink"} alive="loop" />
            <SpeechBubble side="left" className="crossing-bubble">
              {mode === "busy" ? m.ghost.crossingBusy : m.ghost.crossingDetails}
            </SpeechBubble>
          </div>
        </div>
      </div>
      <div className="demo-foot">
        <MotionToggle paused={paused} onToggle={() => setPaused((value) => !value)} m={m.motion} />
      </div>
      <p className="sr-only">{m.crossing.summary}</p>
    </div>
  )
}
