import { ArrowRight, CircleCheck, TriangleAlert } from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import { useEffect, useRef, type KeyboardEvent, type RefObject } from "react"

import { DetailToolbar } from "@/components/detail-toolbar"
import { HowToFixLink } from "@/components/how-to-fix-link"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { RuleDirection } from "@/features/activity-labels"
import { incidentText } from "@/i18n/incident-text"
import { formatRunTime } from "@/lib/activity"
import type { RuleContext } from "@/lib/activity-rule-context"
import { api, type Incident } from "@/lib/api"
import { causeText } from "@/lib/causes"
import { isAdministrator } from "@/lib/people"
import { incidentClosedAt, incidentDetail, incidentDuration, type IncidentStep } from "@/lib/incidents"

type IncidentProps = { incident: Incident; context: RuleContext }

/**
 * One Incident beside the table, as History shows one entry: whether it is still open, what it
 * means or how it closed, its one next step, and when it opened, was last seen, and closed.
 */
export function IncidentDetail({
  incident,
  loading,
  context,
  focusRef,
  onClose,
  onStep,
  onPrevious,
  onNext,
}: {
  incident: Incident | undefined
  /** Whether an incident the list does not hold is still loading on its own. */
  loading: boolean
  context: RuleContext
  focusRef: RefObject<boolean>
  onClose: () => void
  onStep: (step: IncidentStep) => void
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
        <p className="activity-event-status" role="status">
          {loading ? t("activity.incidents.detail.loading") : t("activity.incidents.detail.missing")}
        </p>
      </aside>
    )
  }
  return (
    <aside className="activity-detail" aria-labelledby="incident-detail-title" onKeyDown={close}>
      {toolbar}
      <IncidentSummary incident={incident} context={context} focusRef={focusRef} onStep={onStep} />
      <IncidentFacts incident={incident} context={context} />
    </aside>
  )
}

function IncidentSummary({
  incident,
  context,
  focusRef,
  onStep,
}: IncidentProps & { focusRef: RefObject<boolean>; onStep: (step: IncidentStep) => void }) {
  const headingRef = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    if (!focusRef.current) return
    focusRef.current = false
    headingRef.current?.focus({ preventScroll: true })
  }, [incident, focusRef])
  const { i18n } = context
  const { t } = i18n
  const open = incident.state === "open"
  const { explanation, cause, step, fixUrl } = incidentDetail(i18n, incident, { administrator: useIsAdministrator() })
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
      {(step ?? fixUrl) && (
        <div className="incident-actions">
          {step && (
            <Button variant="outline" size="sm" onClick={() => onStep(step)}>
              {step.label}
              <ArrowRight aria-hidden="true" />
            </Button>
          )}
          {fixUrl && <HowToFixLink href={fixUrl} />}
        </div>
      )}
    </div>
  )
}

/** When a resolved incident closed and how long it lasted, as its row and its details both say. */
export function IncidentClosedTime({ incident, context }: IncidentProps) {
  const { i18n } = context
  const duration = incidentDuration(incident)
  if (!duration) return null
  return (
    <>
      <span className="incident-closed-at">{formatRunTime(i18n, incidentClosedAt(incident))}</span>
      <span className="incident-lasted">
        {i18n.t(`activity.incidents.lasted.${duration.unit}`, { count: duration.count })}
      </span>
    </>
  )
}

/** When it opened, was last seen or closed, and the rule or account it is about. */
function IncidentFacts({ incident, context }: IncidentProps) {
  const { i18n } = context
  const { t } = i18n
  const open = incident.state === "open"
  const lastSeen = open && incident.updated_at !== incident.opened_at
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
      {!open && (
        <div>
          <dt>{t("activity.incidents.detail.closed")}</dt>
          <dd><IncidentClosedTime incident={incident} context={context} /></dd>
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

/** Whether the signed-in User administers the installation, from the session the app already holds. */
function useIsAdministrator(): boolean {
  const session = useQuery({ queryKey: ["session"], queryFn: api.session })
  return isAdministrator(session.data?.user)
}
