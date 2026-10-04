import { ArrowRight } from "lucide-react"
import type { KeyboardEvent, MouseEvent } from "react"

import { EventWhen } from "@/components/activity-event"
import { HappenedLabel } from "@/features/activity-labels"
import { useI18n } from "@/i18n/provider"
import { eventCell, formatClockTime, formatDay, type ActivityDayGroup, type EventCell } from "@/lib/activity"
import { activitySearch, type ActivityLocationState } from "@/lib/activity-location"
import { ruleNames, type RuleContext } from "@/lib/activity-rule-context"
import type { AuditEntry } from "@/lib/api"
import { isPlainLeftClick } from "@/lib/navigation"

export function ActivityTable({
  days,
  context,
  state,
  showRuleColumn,
  onOpen,
  onFilterRule,
  onStep,
}: {
  days: ActivityDayGroup[]
  context: RuleContext
  state: ActivityLocationState
  showRuleColumn: boolean
  onOpen: (entry: AuditEntry) => void
  onFilterRule: (ruleId: string) => void
  onStep: (rowLink: string | undefined) => void
}) {
  const { t } = useI18n()
  const columns = showRuleColumn ? 4 : 3

  function moveSelection(event: KeyboardEvent<HTMLTableElement>) {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return
    const target = event.target as HTMLElement
    if (!target.dataset.rowLink) return
    const links = [...event.currentTarget.querySelectorAll<HTMLElement>("[data-row-link]")]
    const next = links[links.indexOf(target) + (event.key === "ArrowDown" ? 1 : -1)]
    if (!next) return
    event.preventDefault()
    next.focus()
    onStep(next.dataset.rowLink)
  }

  return (
    // Explicit roles keep table semantics where narrow screens restyle the rows.
    <table className="activity-table" role="table" onKeyDown={moveSelection}>
      <caption className="sr-only">{t("activity.history.caption")}</caption>
      <thead role="rowgroup">
        <tr role="row">
          <th scope="col" role="columnheader" className="activity-col-time">{t("activity.history.column.time")}</th>
          <th scope="col" role="columnheader" className="activity-col-event">{t("activity.history.column.event")}</th>
          <th scope="col" role="columnheader" className="activity-col-happened">{t("activity.history.column.happened")}</th>
          {showRuleColumn && (
            <th scope="col" role="columnheader" className="activity-col-rule">{t("activity.history.column.rule")}</th>
          )}
        </tr>
      </thead>
      {days.map((day) => (
        <tbody key={day.key} role="rowgroup" className="activity-day">
          <tr role="row">
            <th scope="rowgroup" role="rowheader" colSpan={columns}>{day.day}</th>
          </tr>
          {day.runs.flatMap((run, runIndex) =>
            run.entries.map((entry, entryIndex) => (
              <EntryRow
                key={entry.id}
                entry={entry}
                context={context}
                state={state}
                selected={state.entryId === entry.id}
                showRuleColumn={showRuleColumn}
                runStart={runIndex > 0 && entryIndex === 0}
                onOpen={onOpen}
                onFilterRule={onFilterRule}
              />
            )),
          )}
        </tbody>
      ))}
    </table>
  )
}

function EntryRow({
  entry,
  context,
  state,
  selected,
  showRuleColumn,
  runStart,
  onOpen,
  onFilterRule,
}: {
  entry: AuditEntry
  context: RuleContext
  state: ActivityLocationState
  selected: boolean
  showRuleColumn: boolean
  runStart: boolean
  onOpen: (entry: AuditEntry) => void
  onFilterRule: (ruleId: string) => void
}) {
  const { i18n } = context
  const { t } = i18n
  const names = ruleNames(entry.rule_id, context)
  const cell = eventCell(i18n, entry, names)
  const href = `${window.location.pathname}${activitySearch({ ...state, entryId: entry.id })}`
  const follow = (event: MouseEvent<HTMLAnchorElement>) => {
    if (!isPlainLeftClick(event)) return
    event.preventDefault()
    onOpen(entry)
  }
  return (
    <tr
      role="row"
      className={runStart ? "activity-row activity-run-start" : "activity-row"}
      data-selected={selected}
      // The event link is the row's keyboard target; the rest of the row is a larger mouse target.
      onClick={(event) => {
        if (!(event.target as HTMLElement).closest("a, button")) onOpen(entry)
      }}
    >
      <td role="cell" className="activity-col-time">
        <time dateTime={entry.occurred_at} aria-hidden="true">{formatClockTime(i18n, entry.occurred_at)}</time>
        <span className="sr-only">
          {t("activity.row.spokenTime", { time: formatClockTime(i18n, entry.occurred_at), day: formatDay(i18n, entry.occurred_at) })}
        </span>
      </td>
      <td role="cell" className="activity-col-event">
        <a
          href={href}
          className="activity-row-link"
          data-row-link={entry.id}
          aria-current={selected ? "true" : undefined}
          onClick={follow}
        >
          <EventCellContent cell={cell} />
        </a>
      </td>
      <td role="cell" className="activity-col-happened">
        <HappenedLabel entry={entry} names={names} />
      </td>
      {showRuleColumn && (
        <td role="cell" className="activity-col-rule">
          <button
            type="button"
            className="activity-rule-name"
            onClick={() => onFilterRule(entry.rule_id)}
            aria-label={
              names
                ? t("activity.row.filterRule", { source: names.source, destination: names.destination })
                : t("activity.row.filterRemovedRule")
            }
          >
            {names ? (
              <>
                <span>{names.source}</span>
                <ArrowRight aria-hidden="true" />
                <span>{names.destination}</span>
              </>
            ) : (
              <span>{t("activity.removedRule")}</span>
            )}
          </button>
        </td>
      )}
    </tr>
  )
}

function EventCellContent({ cell }: { cell: EventCell }) {
  if (cell.state === "unavailable") {
    return (
      <span className="activity-event-cell activity-event-cell-muted">
        <span className="activity-event-title">{cell.label}</span>
        {cell.note && <span className="activity-event-when">{cell.note}</span>}
      </span>
    )
  }
  return (
    <span className="activity-event-cell">
      <span className="activity-event-title">{cell.title}</span>
      <EventWhen cell={cell} />
    </span>
  )
}
