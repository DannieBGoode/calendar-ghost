import { ArrowRight, CircleCheck, TriangleAlert } from "lucide-react"
import { skipToken, useQuery } from "@tanstack/react-query"
import { useRef, type MouseEvent } from "react"

import { GhostMark } from "@/components/ghost-mark"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { IncidentClosedTime, IncidentDetail } from "@/features/activity-incident-details"
import { incidentText } from "@/i18n/incident-text"
import { formatRunTime } from "@/lib/activity"
import { ruleNames, type RuleContext } from "@/lib/activity-rule-context"
import { api, type Incident } from "@/lib/api"
import type { IncidentStep } from "@/lib/incidents"
import { appPathForIncident, isPlainLeftClick } from "@/lib/navigation"

type IncidentProps = { incident: Incident; context: RuleContext }

/** The incidents listed so far, and whether the server holds older ones. */
export type IncidentPages = {
  items: Incident[]
  more: boolean
  loadingMore: boolean
  loadMore: () => void
}
type OnSelect = (incidentId: string | null, history: "push" | "replace") => void

/**
 * Every Incident the installation keeps, in two groups: open ones first, then resolved ones as
 * evidence. Selecting one opens it beside the table, at its own address, as History opens an entry.
 */
export function IncidentsSection({
  incidents,
  selectedId,
  context,
  onSelect,
  onStep,
}: {
  incidents: IncidentPages
  selectedId: string | null
  context: RuleContext
  onSelect: OnSelect
  onStep: (step: IncidentStep) => void
}) {
  const { t } = context.i18n
  const focusDetail = useRef(false)
  const { items, more } = incidents
  const open = items.filter((incident) => incident.state === "open")
  const resolved = items.filter((incident) => incident.state !== "open")
  const ordered = [...open, ...resolved]
  const index = ordered.findIndex((incident) => incident.id === selectedId)
  const selected = useSelectedIncident(selectedId, ordered[index])
  const detailOpen = selectedId !== null

  function select(incident: Incident) {
    focusDetail.current = true
    onSelect(incident.id, detailOpen ? "replace" : "push")
  }

  function step(incident: Incident | undefined) {
    if (incident) onSelect(incident.id, "replace")
  }

  function close() {
    const closing = selectedId
    onSelect(null, "push")
    // Return focus to the row the details described.
    requestAnimationFrame(() => document.querySelector<HTMLElement>(`[data-incident-link="${closing}"]`)?.focus())
  }

  if (items.length === 0) {
    return (
      <section className="workflow activity-section page-card" aria-label={t("activity.incidents.title")}>
        <div className="empty-panel">
          <GhostMark className="empty-ghost" />
          <h2>{t("activity.incidents.empty.title")}</h2>
          <p>{t("activity.incidents.empty.body")}</p>
        </div>
      </section>
    )
  }

  return (
    <section className="workflow activity-section page-card" aria-label={t("activity.incidents.title")}>
      <div className="activity-layout" data-detail={detailOpen}>
        <div className="activity-table-wrap incidents-list">
          <IncidentsTable
            open={open}
            resolved={resolved}
            more={more}
            selectedId={selectedId}
            showRuleColumn={true}
            context={context}
            onSelect={select}
          />
          {more && (
            <Button variant="outline" className="activity-more" onClick={incidents.loadMore} disabled={incidents.loadingMore}>
              {incidents.loadingMore ? t("activity.incidents.loadingOlder") : t("activity.incidents.loadOlder")}
            </Button>
          )}
        </div>
        {detailOpen && (
          <IncidentDetail
            incident={selected.incident}
            loading={selected.loading}
            context={context}
            focusRef={focusDetail}
            onClose={close}
            onStep={onStep}
            onPrevious={index > 0 ? () => step(ordered[index - 1]) : undefined}
            onNext={index >= 0 && index < ordered.length - 1 ? () => step(ordered[index + 1]) : undefined}
          />
        )}
      </div>
    </section>
  )
}

function IncidentsTable({
  open,
  resolved,
  more,
  selectedId,
  showRuleColumn,
  context,
  onSelect,
}: {
  open: Incident[]
  resolved: Incident[]
  /** Whether older incidents are still to load, so the last group's count is a floor. */
  more: boolean
  selectedId: string | null
  showRuleColumn: boolean
  context: RuleContext
  onSelect: (incident: Incident) => void
}) {
  const { t } = context.i18n
  const columns = showRuleColumn ? 4 : 3
  const group = (state: "open" | "resolved", items: Incident[]) =>
    items.length > 0 && (
      <tbody role="rowgroup" className="incident-group" data-state={state}>
        <tr role="row">
          <th scope="rowgroup" role="rowheader" colSpan={columns}>
            <span className="incident-group-label">
              {state === "open" ? <TriangleAlert aria-hidden="true" /> : <CircleCheck aria-hidden="true" />}
              {groupLabel(t, state, items.length, more && (state === "resolved" || resolved.length === 0))}
            </span>
          </th>
        </tr>
        {items.map((incident) => (
          <IncidentRow
            key={incident.id}
            incident={incident}
            context={context}
            selected={incident.id === selectedId}
            showRuleColumn={showRuleColumn}
            onSelect={onSelect}
          />
        ))}
      </tbody>
    )
  return (
    <table className="incidents-table" role="table">
      <caption className="sr-only">{t("activity.incidents.caption")}</caption>
      <colgroup>
        <col className="col-opened" />
        <col className="col-incident" />
        {showRuleColumn && <col className="col-rule" />}
        <col className="col-closed" />
      </colgroup>
      <thead role="rowgroup">
        <tr role="row">
          <th scope="col" role="columnheader">{t("activity.incidents.column.opened")}</th>
          <th scope="col" role="columnheader">{t("activity.incidents.column.incident")}</th>
          {showRuleColumn && <th scope="col" role="columnheader">{t("activity.incidents.column.rule")}</th>}
          <th scope="col" role="columnheader">{t("activity.incidents.column.closed")}</th>
        </tr>
      </thead>
      {group("open", open)}
      {group("resolved", resolved)}
    </table>
  )
}

function IncidentRow({
  incident,
  context,
  selected,
  showRuleColumn,
  onSelect,
}: IncidentProps & { selected: boolean; showRuleColumn: boolean; onSelect: (incident: Incident) => void }) {
  const { i18n } = context
  const { t } = i18n
  const StateIcon = incident.state === "open" ? TriangleAlert : CircleCheck
  const follow = (event: MouseEvent<HTMLAnchorElement>) => {
    if (!isPlainLeftClick(event)) return
    event.preventDefault()
    onSelect(incident)
  }
  return (
    <tr
      role="row"
      className="incident-row"
      data-selected={selected}
      // The incident link is the row's keyboard target; the rest of the row is a larger mouse target.
      onClick={(event) => {
        if (!(event.target as HTMLElement).closest("a, button")) onSelect(incident)
      }}
    >
      <td role="cell" className="incident-col-time" data-label={t("activity.incidents.column.opened")}>
        {formatRunTime(i18n, incident.opened_at)}
      </td>
      <td role="cell" className="incident-col-what">
        <a
          href={appPathForIncident(incident.id)}
          className="incident-link"
          data-incident-link={incident.id}
          aria-current={selected ? "true" : undefined}
          onClick={follow}
        >
          <StateIcon className="incident-state-icon" aria-hidden="true" />
          <span>{incidentText(i18n, incident)}</span>
        </a>
      </td>
      {showRuleColumn && (
        <td role="cell" className="incident-col-rule" data-label={t("activity.incidents.column.rule")}>
          <IncidentSubject incident={incident} context={context} />
        </td>
      )}
      <td role="cell" className="incident-col-time" data-label={t("activity.incidents.column.closed")}>
        <IncidentClosed incident={incident} context={context} />
      </td>
    </tr>
  )
}

/** When it closed and how long it lasted; the tab's ochre count, repeated, while it is open. */
function IncidentClosed({ incident, context }: IncidentProps) {
  if (incident.state !== "open") return <IncidentClosedTime incident={incident} context={context} />
  return (
    <Badge variant="attention" className="incident-still-open">
      {context.i18n.t("activity.incidents.stillOpen")}
    </Badge>
  )
}

/** The rule an Incident is about, by its calendars; an account's own Incident names the account. */
function IncidentSubject({ incident, context }: IncidentProps) {
  const { t } = context.i18n
  if (incident.rule_id) {
    const names = ruleNames(incident.rule_id, context)
    if (!names) return <span className="incident-muted">{t("activity.removedRule")}</span>
    return (
      <span className="incident-rule-names">
        <span>{names.source}</span>
        <ArrowRight aria-hidden="true" />
        <span>{names.destination}</span>
      </span>
    )
  }
  const account = incident.account_id ? context.accountsById.get(incident.account_id) : undefined
  return <span>{account?.email ?? t("activity.incidents.installation")}</span>
}

const GROUP_LABELS = {
  open: { all: "activity.incidents.group.open", floor: "activity.incidents.group.openMore" },
  resolved: { all: "activity.incidents.group.resolved", floor: "activity.incidents.group.resolvedMore" },
} as const

/** "2 resolved", or "100+ resolved" while older ones are still to load. */
function groupLabel(t: RuleContext["i18n"]["t"], state: "open" | "resolved", count: number, floor: boolean): string {
  return t(GROUP_LABELS[state][floor ? "floor" : "all"], { count })
}

/** The selected incident, from the listed ones or, when they do not hold it, on its own. */
function useSelectedIncident(selectedId: string | null, listed: Incident | undefined) {
  // A link can name an incident older than the ones listed so far.
  const direct = useQuery({
    queryKey: ["incidents", selectedId],
    queryFn: selectedId === null ? skipToken : () => api.incident(selectedId),
    enabled: listed === undefined,
    retry: false,
  })
  const incident = listed ?? (direct.data?.id === selectedId ? direct.data : undefined)
  return { incident, loading: incident === undefined && direct.isFetching }
}
