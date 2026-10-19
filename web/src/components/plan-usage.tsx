import { Clock, Info, TriangleAlert, Zap } from "lucide-react"
import type { ReactNode } from "react"

import { Badge } from "@/components/ui/badge"
import { Meter } from "@/components/ui/meter"
import { rich } from "@/i18n/rich"
import type { UsageRow } from "@/lib/plan-usage"

/** Renders the `<link>` in a note, to where room is made, such as Connections. */
type NoteLink = (text: string) => ReactNode

/**
 * How much of a Plan someone uses: one row per limit with its name and what counts, a meter where
 * the limit is a number, the count against it ("1 of 1"), and a chip at or past it. Past an
 * enforced limit the meter turns Attention Ochre with stripes, the chip carries the attention icon,
 * and a sentence below says what keeps working, so color is never the only sign. At a limit, a
 * quiet sentence with an information icon may say what to do before adding another.
 */
export function PlanUsage({ rows, noteLink }: { rows: readonly UsageRow[]; noteLink?: NoteLink }) {
  return (
    <div className="plan-usage">
      {rows.map((row) => (
        <UsageLine key={row.limit} row={row} noteLink={noteLink} />
      ))}
    </div>
  )
}

function UsageLine({ row, noteLink }: { row: UsageRow; noteLink: NoteLink | undefined }) {
  const over = row.chip?.tone === "attention"
  const { note } = row
  return (
    <div className="plan-usage-row" data-over={over || undefined}>
      <div className="plan-usage-what">
        <p className="plan-usage-name">{row.title}</p>
        <p className="plan-usage-hint">{row.hint}</p>
      </div>
      <div className="plan-usage-gauge">
        <UsageGauge row={row} />
      </div>
      <UsageState row={row} over={over} />
      {note && (
        <p className="plan-usage-note" data-tone={note.tone}>
          {note.tone === "attention" ? <TriangleAlert aria-hidden="true" /> : <Info aria-hidden="true" />}
          <span>{rich(note.text, noteLink ? { link: noteLink } : {})}</span>
        </p>
      )}
    </div>
  )
}

/** A meter where the limit is a number; otherwise what the row says in words, if anything. */
function UsageGauge({ row }: { row: UsageRow }) {
  const { meter } = row
  if (meter) return <Meter aria-label={row.title} value={meter.value} max={meter.max} valueText={meter.valueText} tone={meter.tone} />
  return row.detail ? <p className="plan-usage-detail">{row.detail}</p> : null
}

/** The count against the limit, or how soon calendars sync with its icon, and the chip at or past it. */
function UsageState({ row, over }: { row: UsageRow; over: boolean }) {
  const { chip, speed } = row
  return (
    <div className="plan-usage-state">
      <span className="plan-usage-value" data-quiet={row.quiet || undefined} data-over={over || undefined}>
        {speed && (speed === "instant" ? <Zap aria-hidden="true" /> : <Clock aria-hidden="true" />)}
        {row.value}
      </span>
      {chip && (
        <Badge variant={over ? "attention" : "neutral"} className="plan-usage-chip" data-tone={chip.tone}>
          {over && <TriangleAlert aria-hidden="true" />}
          {chip.text}
        </Badge>
      )}
    </div>
  )
}
