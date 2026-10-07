import { ArrowRight, ChevronDown, ChevronUp } from "lucide-react"
import { useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { RuleDirection } from "@/features/activity-labels"
import { incidentText } from "@/i18n/incident-text"
import { formatRunTime } from "@/lib/activity"
import { incidentRuleState, type RuleContext } from "@/lib/activity-rule-context"
import type { Incident } from "@/lib/api"
import { incidentClosedAt, incidentGuidance, incidentResolution, type IncidentAction } from "@/lib/incidents"

/** The rule an Incident is about; an account's own Incident, such as a lapse, names the account. */
function IncidentRule({ incident, context }: { incident: Incident; context: RuleContext }) {
  const { t } = context.i18n
  if (incident.rule_id) return <RuleDirection ruleId={incident.rule_id} context={context} />
  const account = incident.account_id ? context.accountsById.get(incident.account_id) : undefined
  return <span>{account?.email ?? t("activity.incidents.installation")}</span>
}

/** Only incidents that still need attention lead the page, each with its next step. */
export function OpenIncidents({
  incidents,
  context,
  onAction,
}: {
  incidents: Incident[]
  context: RuleContext
  onAction: (action: IncidentAction) => void
}) {
  const { i18n } = context
  const { t } = i18n
  if (incidents.length === 0) return null
  return (
    <section className="workflow activity-section page-card" aria-labelledby="incidents-title">
      <div className="section-heading">
        <div>
          <h2 id="incidents-title">{t("activity.incidents.title")}</h2>
          <p>{t("activity.incidents.intro")}</p>
        </div>
      </div>
      <ul className="rule-list">
        {incidents.map((incident) => {
          const { detail, action } = incidentGuidance(i18n, incident, incidentRuleState(incident, context))
          return (
            <li className="rule-row incident-row" key={incident.id}>
              <div className="incident-heading">
                <strong>{incidentText(i18n, incident)}</strong>
                <Badge variant="attention">{t("activity.incidents.open")}</Badge>
              </div>
              <div className="activity-run-meta">
                <IncidentRule incident={incident} context={context} />
                <span>{t("activity.incidents.since", { time: formatRunTime(i18n, incident.opened_at) })}</span>
                {incident.updated_at !== incident.opened_at && (
                  <span>{t("activity.incidents.lastSeen", { time: formatRunTime(i18n, incident.updated_at) })}</span>
                )}
              </div>
              {detail && <p className="incident-detail">{detail}</p>}
              {action && (
                <div>
                  <Button variant="outline" size="sm" onClick={() => onAction(action)}>
                    {action.label}
                    <ArrowRight aria-hidden="true" />
                  </Button>
                </div>
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}

/** Resolved incidents are kept as evidence, out of the way until asked for. */
export function ResolvedIncidents({ incidents, context }: { incidents: Incident[]; context: RuleContext }) {
  const { i18n } = context
  const { t } = i18n
  const [open, setOpen] = useState(false)
  if (incidents.length === 0) return null
  return (
    <section className="resolved-incidents" aria-label={t("activity.incidents.resolvedLabel")}>
      <Button
        variant="ghost"
        size="sm"
        className="resolved-incidents-toggle"
        aria-expanded={open}
        aria-controls="resolved-incidents-list"
        onClick={() => setOpen((value) => !value)}
      >
        {open ? <ChevronUp aria-hidden="true" /> : <ChevronDown aria-hidden="true" />}
        {open ? t("activity.incidents.hideResolved") : t("activity.incidents.showResolved", { count: incidents.length })}
      </Button>
      {open && (
        <ul id="resolved-incidents-list" className="rule-list">
          {incidents.map((incident) => {
            const resolution = incidentResolution(i18n, incident)
            return (
              <li className="rule-row incident-row" key={incident.id}>
                <div className="incident-heading">
                  <strong>{incidentText(i18n, incident)}</strong>
                  <Badge variant="neutral">{t("activity.incidents.resolved")}</Badge>
                </div>
                <div className="activity-run-meta">
                  <IncidentRule incident={incident} context={context} />
                  <span>{t("activity.incidents.opened", { time: formatRunTime(i18n, incident.opened_at) })}</span>
                  <span>{t("activity.incidents.closed", { time: formatRunTime(i18n, incidentClosedAt(incident)) })}</span>
                </div>
                {resolution && <p className="incident-detail">{resolution}</p>}
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
