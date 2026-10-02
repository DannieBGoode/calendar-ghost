import {
  ArrowRight,
  Check,
  CircleSlash,
  Pin,
  Plus,
  RefreshCw,
  Repeat,
  Settings2,
  ShieldAlert,
  Trash2,
  Undo2,
  type LucideIcon,
} from "lucide-react"

import type { EventCell, Happened, HappenedIcon } from "@/lib/activity"

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

const HAPPENED_ICONS: Record<HappenedIcon, LucideIcon> = {
  added: Plus,
  updated: RefreshCw,
  repaired: Undo2,
  removed: Trash2,
  kept: Pin,
  current: Check,
  skipped: CircleSlash,
  blocked: ShieldAlert,
  rule: Settings2,
}

/** What was observed, then what Calendar Ghost did; the outcome carries the tone. */
export function HappenedLine({ happened, suffix }: { happened: Happened; suffix?: string }) {
  const Icon = HAPPENED_ICONS[happened.icon]
  return (
    <span className="activity-happened" data-tone={happened.tone}>
      <Icon aria-hidden="true" />
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

