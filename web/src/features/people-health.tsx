import { useQuery } from "@tanstack/react-query"

import { Check } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { useI18n } from "@/i18n/provider"
import { api, type InstallationHealthReport, type Verdict } from "@/lib/api"
import { VERDICTS } from "@/lib/operator-overview"
import { VerdictBadge, VerdictIcon } from "@/components/verdict-badge"

const REFRESH_INTERVAL = 60_000

/**
 * Installation Health above People: the installation's one verdict, how many people are in each
 * sync status, and incidents about the installation itself. It names nobody. Each count filters
 * the list below by that status; pressing it again shows everyone.
 */
export function InstallationHealthSummary({
  verdict,
  now,
  onFilter,
}: {
  verdict: Verdict | ""
  now: number
  onFilter: (verdict: Verdict | "") => void
}) {
  const { t } = useI18n()
  const health = useQuery({
    queryKey: ["installation-health"],
    queryFn: api.installationHealth,
    refetchInterval: REFRESH_INTERVAL,
  })
  return (
    <section className="workflow page-card installation-health" aria-labelledby="installation-health-title">
      <div className="section-heading">
        <h2 id="installation-health-title">{t("people.health.title")}</h2>
      </div>
      {health.isPending && <Skeleton className="h-16 w-full" />}
      {health.error && (
        <div className="inline-error integration-load-error" role="alert">
          <span>{t("people.health.loadFailure")}</span>
          <Button type="button" variant="outline" onClick={() => void health.refetch()}>
            {t("people.health.tryAgain")}
          </Button>
        </div>
      )}
      {health.data && <HealthReport report={health.data} verdict={verdict} now={now} onFilter={onFilter} />}
    </section>
  )
}

function HealthReport({
  report,
  verdict,
  now,
  onFilter,
}: {
  report: InstallationHealthReport
  verdict: Verdict | ""
  now: number
  onFilter: (verdict: Verdict | "") => void
}) {
  const i18n = useI18n()
  const { t } = i18n
  const counted = VERDICTS.filter((each) => (report.users[each] ?? 0) > 0)
  return (
    <div className="installation-health-report">
      <div className="user-overview-verdict">
        <VerdictBadge verdict={report.status} />
        <p>{t(`people.health.summary.${report.status}`)}</p>
      </div>
      {report.incidents.map((incident) => (
        <p key={incident.kind} className="user-overview-muted">
          {t("people.health.schedulerStalled", { relative: i18n.format.relative(incident.since, now) })}
        </p>
      ))}
      {counted.length > 0 && (
        <div className="installation-health-counts" role="group" aria-label={t("people.health.countsLabel")}>
          {counted.map((each) => {
            const label = t(`people.verdicts.${each}`)
            const pressed = verdict === each
            return (
              <Button
                key={each}
                type="button"
                variant="outline"
                className="health-count"
                aria-pressed={pressed}
                onClick={() => onFilter(pressed ? "" : each)}
              >
                {pressed ? <Check aria-hidden="true" /> : <VerdictIcon verdict={each} />}
                {t("people.health.count", { verdict: label, count: report.users[each] ?? 0 })}
              </Button>
            )
          })}
        </div>
      )}
      {report.disabled_users > 0 && (
        <p className="user-overview-muted">{t("people.health.disabled", { count: report.disabled_users })}</p>
      )}
    </div>
  )
}
