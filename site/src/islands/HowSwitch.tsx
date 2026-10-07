import { useState } from "react"
import type { AvatarUrls } from "../avatars"
import type { CrossingMode } from "../demo/crossing"
import type { Messages } from "../i18n"
import { iconMarkup, type IconName } from "../icons"

const MODES: readonly CrossingMode[] = ["busy", "details"]

/** Step 3's three preview rows: Sam's week, each at the clock time it already starts at in
 * `SAM_WEEK` (Monday's Dentist, Tuesday's Gym, Thursday's Therapy). */
const PREVIEWS = [
  { dayIndex: 0, time: "3:00 PM", eventKey: "dentist" },
  { dayIndex: 1, time: "12:00 PM", eventKey: "gym" },
  { dayIndex: 3, time: "1:00 PM", eventKey: "therapy" },
] as const satisfies readonly { dayIndex: number; time: string; eventKey: keyof Messages["demo"]["events"] }[]

/** A Lucide mark inline, `display: contents` so it takes its parent's flex or grid place exactly
 * like `components/Icon.astro`'s bare SVG does (an island cannot use that Astro-only component). */
function Mark({ name, className }: { name: IconName; className: string }) {
  return <span style={{ display: "contents" }} dangerouslySetInnerHTML={{ __html: iconMarkup(name, className) }} />
}

/**
 * "How it works" strip, steps 2 and 3: the switch picks what a rule sends (Busy-Only Projection
 * or Details Projection, CONTEXT.md), and step 3's preview follows it. Both steps live in one
 * island so they share the state (same control pattern as the Crossing switch, `islands/Crossing.
 * tsx`: a button group with `aria-pressed`, 44px targets). Server-rendered with Busy only picked,
 * so the page reads correctly, and the switch is simply inert, without JavaScript.
 */
export function HowSwitch({
  m,
  avatars,
}: {
  m: Pick<Messages, "crossing" | "demo" | "how" | "howStrip">
  avatars: AvatarUrls
}) {
  const [mode, setMode] = useState<CrossingMode>("busy")
  const stepRule = m.how.steps[1]
  const stepPreview = m.how.steps[2]

  return (
    <>
      <li>
        <div className="how-frag how-frag-rule">
          <span className="how-route" aria-hidden="true">
            <img className="avatar" src={avatars.personal} alt="" width={28} height={28} />
            <b>{m.demo.calendars.personal}</b>
            <Mark name="arrowRight" className="how-route-arrow" />
            <img className="avatar" src={avatars.work} alt="" width={28} height={28} />
            <b>{m.demo.calendars.work}</b>
          </span>
          <span className="how-segment" role="group" aria-label={m.crossing.switchLabel}>
            {MODES.map((option) => (
              <button key={option} type="button" aria-pressed={mode === option} onClick={() => setMode(option)}>
                {option === "busy" ? m.crossing.busyOnly : m.crossing.withDetails}
              </button>
            ))}
          </span>
        </div>
        <p className="how-step-n" aria-hidden="true">
          2
        </p>
        <h3>{stepRule.title}</h3>
        <p>{stepRule.body}</p>
      </li>
      <li>
        <div className="how-frag how-frag-preview" aria-hidden="true">
          <span className="how-preview-head">
            <Mark name="eye" className="how-preview-icon" />
            {m.howStrip.previewRule}
          </span>
          {PREVIEWS.map(({ dayIndex, time, eventKey }) => (
            <span className="how-preview-row" key={eventKey}>
              <span className={mode === "busy" ? "how-preview-busy" : "how-preview-event"}>
                {mode === "busy" ? m.demo.busy : m.demo.events[eventKey].title}
              </span>
              <span>
                {m.demo.days[dayIndex]} {time}
              </span>
            </span>
          ))}
          <span className="how-preview-start">{m.howStrip.startSyncing}</span>
        </div>
        <p className="how-step-n" aria-hidden="true">
          3
        </p>
        <h3>{stepPreview.title}</h3>
        <p>{stepPreview.body}</p>
      </li>
    </>
  )
}
