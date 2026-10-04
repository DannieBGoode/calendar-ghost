import { ArrowRight, ChevronDown, ChevronUp } from "lucide-react"
import { useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { RuleDirection } from "@/features/activity-labels"
import { formatRunTime } from "@/lib/activity"
import { incidentRuleState, type RuleContext } from "@/lib/activity-rule-context"
import type { Incident } from "@/lib/api"
import { incidentClosedAt, incidentGuidance, incidentResolution, type IncidentAction } from "@/lib/incidents"
import { plural } from "@/lib/rule-change"

function IncidentRule({ incident, context }: { incident: Incident; context: RuleContext }) {
  return incident.rule_id ? <RuleDirection ruleId={incident.rule_id} context={context} /> : <span>Installation</span>
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
  if (incidents.length === 0) return null
  return (
    <section className="workflow activity-section page-card" aria-labelledby="incidents-title">
      <div className="section-heading">
        <div>
          <h2 id="incidents-title">Incidents</h2>
          <p>Each stays open until Calendar Ghost confirms the problem is gone.</p>
        </div>
      </div>
      <ul className="rule-list">
        {incidents.map((incident) => {
          const { detail, action } = incidentGuidance(incident, incidentRuleState(incident, context))
          return (
            <li className="rule-row incident-row" key={incident.id}>
              <div className="incident-heading">
                <strong>{incident.summary}</strong>
                <Badge variant="attention">Open</Badge>
              </div>
              <div className="activity-run-meta">
                <IncidentRule incident={incident} context={context} />
                <span>Since {formatRunTime(incident.opened_at)}</span>
                {incident.updated_at !== incident.opened_at && <span>Last seen {formatRunTime(incident.updated_at)}</span>}
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
  const [open, setOpen] = useState(false)
  if (incidents.length === 0) return null
  return (
    <section className="resolved-incidents" aria-label="Resolved incidents">
      <Button
        variant="ghost"
        size="sm"
        className="resolved-incidents-toggle"
        aria-expanded={open}
        aria-controls="resolved-incidents-list"
        onClick={() => setOpen((value) => !value)}
      >
        {open ? <ChevronUp aria-hidden="true" /> : <ChevronDown aria-hidden="true" />}
        {open ? "Hide resolved incidents" : `Show ${plural(incidents.length, "resolved incident")}`}
      </Button>
      {open && (
        <ul id="resolved-incidents-list" className="rule-list">
          {incidents.map((incident) => {
            const resolution = incidentResolution(incident)
            return (
              <li className="rule-row incident-row" key={incident.id}>
                <div className="incident-heading">
                  <strong>{incident.summary}</strong>
                  <Badge variant="neutral">Resolved</Badge>
                </div>
                <div className="activity-run-meta">
                  <IncidentRule incident={incident} context={context} />
                  <span>Opened {formatRunTime(incident.opened_at)}</span>
                  <span>Closed {formatRunTime(incidentClosedAt(incident))}</span>
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
