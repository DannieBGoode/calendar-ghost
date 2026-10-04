import { ArrowRight, Repeat } from "lucide-react"

import { ChangeSign } from "@/components/change-sign"
import { useI18n } from "@/i18n/provider"
import type { MessageKey } from "@/i18n/types"
import type { EventCell, Happened } from "@/lib/activity"

const SCOPE_LABELS: Record<"series" | "occurrence", MessageKey> = {
  series: "activity.event.scope.series",
  occurrence: "activity.event.scope.occurrence",
}

export function EventWhen({ cell }: { cell: Extract<EventCell, { state: "event" }> }) {
  const { t } = useI18n()
  const { note, when } = cell
  return (
    <span className="activity-event-when">
      {note && when ? t("activity.event.noteAndWhen", { note, when }) : note || when}
      {cell.recurring && (
        <span className="activity-recurring">
          <Repeat aria-hidden="true" /> {t(cell.scope ? SCOPE_LABELS[cell.scope] : "activity.event.repeats")}
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
  const { t } = useI18n()
  return (
    <span className="activity-happened" data-tone={happened.tone}>
      {signed && (
        <span className="activity-sign" data-mark={happened.mark}>
          <ChangeSign mark={happened.mark} />
        </span>
      )}
      <span>
        {happened.trigger ? (
          <>
            {/* The arrow reads as a sentence to screen readers, so they get one. */}
            <span aria-hidden="true">
              <span className="activity-trigger">{happened.trigger}</span>
              <ArrowRight className="activity-happened-arrow" />
              <span className="activity-effect">{happened.effect}</span>
            </span>
            <span className="sr-only">{t("activity.happened.spoken", { trigger: happened.trigger, effect: happened.effect })}</span>
          </>
        ) : (
          <span className="activity-effect">{happened.effect}</span>
        )}
        {suffix && <span className="activity-happened-suffix"> · {suffix}</span>}
      </span>
    </span>
  )
}
