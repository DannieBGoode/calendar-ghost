import { ArrowRight, ChevronRight } from "lucide-react"
import { useState } from "react"

import { ChangeSign } from "@/components/change-sign"
import { useI18n } from "@/i18n/provider"
import type { I18n } from "@/i18n/translator"
import {
  OUTCOME_MARKS,
  isToday,
  isTomorrow,
  outcomeCounts,
  previewOutcome,
  type PlacedItem,
  type PreviewDay,
  type PreviewLayout,
  type PreviewOutcome,
} from "@/lib/rule-preview"
import { destinationNotes, outcomeParts, outcomeText, sourceNotes, whenText } from "@/lib/rule-preview-text"

const COLUMNS = 4
const DAY: Intl.DateTimeFormatOptions = { weekday: "short", day: "numeric", month: "short" }

/** Removals and blocks are the outcomes nobody should miss; the rest are quiet. */
const TONES: Record<PreviewOutcome, "change" | "quiet" | "blocked"> = {
  add: "change",
  update: "change",
  remove: "change",
  current: "quiet",
  blocked: "blocked",
  skipped: "quiet",
}

function dayHeading(i18n: I18n, day: PreviewDay, now: Date): string {
  const date = i18n.format.date(day.date, DAY)
  if (isToday(day.date, now)) return i18n.t("rulePreview.table.today", { date })
  if (isTomorrow(day.date, now)) return i18n.t("rulePreview.table.tomorrow", { date })
  return date
}

export function OutcomeSigns({ parts }: { parts: { outcome: PreviewOutcome; text: string }[] }) {
  return (
    <>
      {parts.map(({ outcome, text }) => (
        <span key={outcome} className="rule-preview-count" data-tone={TONES[outcome]}>
          <span className="activity-sign" data-mark={OUTCOME_MARKS[outcome]}>
            <ChangeSign mark={OUTCOME_MARKS[outcome]} />
          </span>
          {text}
        </span>
      ))}
    </>
  )
}

function Notes({ notes }: { notes: string[] }) {
  if (!notes.length) return null
  return <span className="rule-preview-note">{notes.join(" · ")}</span>
}

function PreviewRow({ placed }: { placed: PlacedItem }) {
  const i18n = useI18n()
  const { item } = placed
  const outcome = previewOutcome(item)
  return (
    <tr role="row" className="rule-preview-row" data-written={item.projection ? "true" : "false"}>
      <td role="cell" className="rule-preview-col-when">{whenText(i18n, placed)}</td>
      <td role="cell" className="rule-preview-col-source">
        <span className="rule-preview-title">{item.title || i18n.t("rulePreview.row.untitled")}</span>
        <Notes notes={sourceNotes(i18n, placed)} />
      </td>
      <td role="cell" className="rule-preview-col-destination">
        {item.projection ? (
          <>
            <ArrowRight aria-hidden="true" className="rule-preview-into" />
            <span className="rule-preview-title">{item.projection.title}</span>
            <Notes notes={destinationNotes(i18n, placed)} />
          </>
        ) : (
          // The outcome beside it says why; sighted readers see an empty cell, others hear this.
          <span className="sr-only">{i18n.t("rulePreview.row.notWritten")}</span>
        )}
      </td>
      <td role="cell" className="rule-preview-col-outcome">
        <span className="activity-happened" data-tone={TONES[outcome]}>
          <span className="activity-sign" data-mark={OUTCOME_MARKS[outcome]}>
            <ChangeSign mark={OUTCOME_MARKS[outcome]} />
          </span>
          <span className="activity-effect">{outcomeText(i18n, item)}</span>
        </span>
      </td>
    </tr>
  )
}

function DayRows({ day, heading }: { day: PreviewDay; heading: string }) {
  return (
    <tbody role="rowgroup" className="rule-preview-day">
      <tr role="row">
        <th scope="rowgroup" role="rowheader" colSpan={COLUMNS}>{heading}</th>
      </tr>
      {day.items.map((placed) => (
        <PreviewRow key={`${placed.item.source_event_id}-${placed.item.original_start ?? ""}`} placed={placed} />
      ))}
    </tbody>
  )
}

/** The past part of the window, folded into one row that says what it holds; a removal opens it. */
function EarlierRows({ days }: { days: PreviewDay[] }) {
  const i18n = useI18n()
  const items = days.flatMap((day) => day.items.map((placed) => placed.item))
  const counts = outcomeCounts(items)
  const [open, setOpen] = useState(() => counts.has("remove") || counts.has("blocked"))
  const first = days[0]
  if (!first) return null
  const title = i18n.t("rulePreview.table.earlier", { date: i18n.format.date(first.date, { day: "numeric", month: "short" }) })
  const countText = i18n.t("rulePreview.table.earlierCount", { count: items.length })
  const parts = outcomeParts(i18n, counts)
  // Spoken as phrases; the visible counts sit in separate boxes with no punctuation between.
  const name = i18n.t("rulePreview.table.earlierName", {
    title,
    counts: i18n.format.unitList([countText, ...parts.map((part) => part.text)]),
  })
  return (
    <>
      <tbody role="rowgroup" className="rule-preview-earlier">
        <tr role="row">
          <th scope="rowgroup" role="rowheader" colSpan={COLUMNS}>
            <button type="button" className="rule-preview-earlier-toggle" aria-label={name} aria-expanded={open} aria-controls={open ? "rule-preview-earlier-days" : undefined} onClick={() => setOpen((value) => !value)}>
              <ChevronRight aria-hidden="true" className="rule-preview-chevron" />
              <span>{title}</span>
              <span className="rule-preview-earlier-counts">
                {countText}
                <OutcomeSigns parts={parts} />
              </span>
            </button>
          </th>
        </tr>
      </tbody>
      {open && (
        <tbody role="rowgroup" id="rule-preview-earlier-days" className="rule-preview-earlier-days">
          {days.flatMap((day) => [
            <tr role="row" key={`${day.key}-heading`} className="rule-preview-earlier-day">
              <th scope="rowgroup" role="rowheader" colSpan={COLUMNS}>{i18n.format.date(day.date, DAY)}</th>
            </tr>,
            ...day.items.map((placed) => (
              <PreviewRow key={`${placed.item.source_event_id}-${placed.item.original_start ?? ""}`} placed={placed} />
            )),
          ])}
        </tbody>
      )}
    </>
  )
}

export function PreviewTable({
  layout,
  source,
  destination,
  now,
  zone,
}: {
  layout: PreviewLayout
  source: string
  destination: string
  now: Date
  /** The browser's time zone, such as "GMT+2", which every time in the table is in. */
  zone: string
}) {
  const i18n = useI18n()
  const { t } = i18n
  return (
    <div className="rule-preview-table-wrap">
      {/* Explicit roles keep table semantics where narrow screens restyle the rows. */}
      <table className="rule-preview-table" role="table">
        <caption className="sr-only">{t("rulePreview.table.caption", { source, destination })}</caption>
        <thead role="rowgroup">
          <tr role="row">
            <th scope="col" role="columnheader" className="rule-preview-col-when">
              {t("rulePreview.table.when")} <span className="rule-preview-role">{zone}</span>
            </th>
            <th scope="col" role="columnheader" className="rule-preview-col-source">
              {source} <span className="rule-preview-role">{t("rulePreview.table.source")}</span>
            </th>
            <th scope="col" role="columnheader" className="rule-preview-col-destination">
              <ArrowRight aria-hidden="true" className="rule-preview-into" />
              {destination} <span className="rule-preview-role">{t("rulePreview.table.destination")}</span>
            </th>
            <th scope="col" role="columnheader" className="rule-preview-col-outcome">{t("rulePreview.table.outcome")}</th>
          </tr>
        </thead>
        {layout.undated.length > 0 && (
          <DayRows
            day={{ key: "undated", date: now, items: layout.undated }}
            heading={t("rulePreview.table.undated", { source })}
          />
        )}
        {layout.earlier.length > 0 && <EarlierRows days={layout.earlier} />}
        {layout.upcoming.map((day) => (
          <DayRows key={day.key} day={day} heading={dayHeading(i18n, day, now)} />
        ))}
        <tbody role="rowgroup" className="rule-preview-later">
          <tr role="row">
            <td role="cell" colSpan={COLUMNS}>
              {t("rulePreview.table.later", { source })}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  )
}
