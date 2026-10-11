import { ArrowRight, CircleCheck, TriangleAlert } from "lucide-react"
import { useEffect, useRef, type KeyboardEvent, type RefObject } from "react"

import { DetailToolbar } from "@/components/detail-toolbar"
import { HowToFixLink } from "@/components/how-to-fix-link"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { RuleDirection } from "@/features/activity-labels"
import { incidentText } from "@/i18n/incident-text"
import { formatRunTime } from "@/lib/activity"
import { incidentRuleState, type RuleContext } from "@/lib/activity-rule-context"
import type { Incident } from "@/lib/api"
import { causeText } from "@/lib/causes"
import { incidentClosedAt, incidentDetail, incidentDuration, type IncidentAction } from "@/lib/incidents"

type IncidentProps = { incident: Incident; context: RuleContext }

/**
 * One Incident beside the table, as History shows one entry: whether it is still open, what it
 * means or how it closed, its one next step, and when it opened, was last seen, and closed.
 */
export function IncidentDetail({
  incident,
  context,
  focusRef,
  onClose,
  onAction,
  onPrevious,
  onNext,
}: {
  incident: Incident | undefined
  context: RuleContext
  focusRef: RefObject<boolean>
  onClose: () => void
  onAction: (action: IncidentAction) => void
  onPrevious?: (() => void) | undefined
  onNext?: (() => void) | undefined
}) {
  const { t } = context.i18n
  const close = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === "Escape") onClose()
  }
  const toolbar = (
    <DetailToolbar
      labels={{
        close: t("activity.detail.close"),
        previous: t("activity.incidents.detail.previous"),
        next: t("activity.incidents.detail.next"),
      }}
      onClose={onClose}
      onPrevious={onPrevious}
      onNext={onNext}
    />
  )
  if (!incident) {
    return (
      <aside className="activity-detail" aria-label={t("activity.incidents.detail.label")} onKeyDown={close}>
        {toolbar}
        <p className="activity-event-status" role="status">{t("activity.incidents.detail.missing")}</p>
      </aside>
    )
  }
  return (
    <aside className="activity-detail" aria-labelledby="incident-detail-title" onKeyDown={close}>
      {toolbar}
      <IncidentSummary incident={incident} context={context} focusRef={focusRef} onAction={onAction} />
      <IncidentFacts incident={incident} context={context} />
    </aside>
  )
}

function IncidentSummary({
  incident,
  context,
  focusRef,
  onAction,
}: IncidentProps & { focusRef: RefObject<boolean>; onAction: (action: IncidentAction) => void }) {
  const headingRef = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    if (!focusRef.current) return
    focusRef.current = false
    headingRef.current?.focus({ preventScroll: true })
  }, [incident, focusRef])
  const { i18n } = context
  const { t } = i18n
  const open = incident.state === "open"
  const { explanation, cause, action, fixUrl } = incidentDetail(i18n, incident, incidentRuleState(incident, context))
  return (
    <div className="activity-detail-heading">
      <Badge variant={open ? "attention" : "neutral"}>
        {open ? <TriangleAlert aria-hidden="true" /> : <CircleCheck aria-hidden="true" />}
        {open ? t("activity.incidents.status.open") : t("activity.incidents.status.resolved")}
      </Badge>
      <h2 id="incident-detail-title" ref={headingRef} tabIndex={-1}>
        {incidentText(i18n, incident)}
      </h2>
      {explanation && <p className="incident-explanation">{explanation}</p>}
      {cause && <p className="activity-explanation">{causeText(i18n, cause)}</p>}
      {(action ?? fixUrl) && (
        <div className="incident-actions">
          {action && (
            <Button variant="outline" size="sm" onClick={() => onAction(action)}>
              {action.label}
              <ArrowRight aria-hidden="true" />
            </Button>
          )}
          {fixUrl && <HowToFixLink href={fixUrl} />}
        </div>
      )}
    </div>
  )
}

/** When it opened, was last seen or closed, and the rule or account it is about. */
function IncidentFacts({ incident, context }: IncidentProps) {
  const { i18n } = context
  const { t } = i18n
  const duration = incidentDuration(incident)
  const lastSeen = incident.state === "open" && incident.updated_at !== incident.opened_at
  return (
    <dl className="activity-detail-facts">
      <div>
        <dt>{t("activity.incidents.detail.opened")}</dt>
        <dd>{formatRunTime(i18n, incident.opened_at)}</dd>
      </div>
      {lastSeen && (
        <div>
          <dt>{t("activity.incidents.detail.lastSeen")}</dt>
          <dd>{formatRunTime(i18n, incident.updated_at)}</dd>
        </div>
      )}
      {duration && (
        <div>
          <dt>{t("activity.incidents.detail.closed")}</dt>
          <dd>
            <span>{formatRunTime(i18n, incidentClosedAt(incident))}</span>
            <span className="incident-lasted">{t(`activity.incidents.lasted.${duration.unit}`, { count: duration.count })}</span>
          </dd>
        </div>
      )}
      <IncidentSubjectFact incident={incident} context={context} />
    </dl>
  )
}

/** The rule with its accounts, or the account a lapse belongs to; installation incidents name neither. */
function IncidentSubjectFact({ incident, context }: IncidentProps) {
  const { t } = context.i18n
  if (incident.rule_id) {
    return (
      <div>
        <dt>{t("activity.detail.rule")}</dt>
        <dd><RuleDirection ruleId={incident.rule_id} context={context} /></dd>
      </div>
    )
  }
  const account = incident.account_id ? context.accountsById.get(incident.account_id) : undefined
  if (!account) return null
  return (
    <div>
      <dt>{t("activity.incidents.detail.account")}</dt>
      <dd>{account.email}</dd>
    </div>
  )
}
