import { ArrowRight, Repeat } from "lucide-react"

import { ChangeSign } from "@/components/change-sign"
import type { EventCell, Happened } from "@/lib/activity"

const SCOPE_LABELS = { series: "Whole series", occurrence: "One occurrence" } as const

export function EventWhen({ cell }: { cell: Extract<EventCell, { state: "event" }> }) {
  return (
    <span className="activity-event-when">
      {[cell.note, cell.when].filter(Boolean).join(" · ")}
      {cell.recurring && (
        <span className="activity-recurring">
          <Repeat aria-hidden="true" /> {cell.scope ? SCOPE_LABELS[cell.scope] : "Repeats"}
        </span>
      )}
    </span>
  )
}

/** What was observed, then what Calendar Ghost did; the outcome carries the tone. */
export function HappenedLine({
  happened,
  suffix,
  signed = true,
}: {
  happened: Happened
  suffix?: string | undefined
  /** False where a marker beside the line already shows the sign. */
  signed?: boolean
}) {
  return (
    <span className="activity-happened" data-tone={happened.tone}>
      {signed && (
        <span className="activity-sign" data-mark={happened.mark}>
          <ChangeSign mark={happened.mark} />
        </span>
      )}
      <span>
        {happened.trigger && (
          <>
            <span className="activity-trigger">{happened.trigger}</span>
            <ArrowRight aria-hidden="true" className="activity-happened-arrow" />
            <span className="sr-only">, so </span>
          </>
        )}
        <span className="activity-effect">{happened.effect}</span>
        {suffix && <span className="activity-happened-suffix"> · {suffix}</span>}
      </span>
    </span>
  )
}

