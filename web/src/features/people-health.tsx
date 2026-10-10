import { useQuery } from "@tanstack/react-query"
import { CheckCircle2, ChevronDown, CircleHelp, Lightbulb, ShieldAlert, UserX } from "lucide-react"

import { HowToFixLink } from "@/components/how-to-fix-link"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { VerdictBadge, VerdictIcon } from "@/components/verdict-badge"
import { useI18n } from "@/i18n/provider"
import type { I18n } from "@/i18n/translator"
import { api, type InstallationHealthReport, type InstallationHint, type PeopleQuery } from "@/lib/api"
import { hintText, troubleshootingUrl } from "@/lib/causes"
import { VERDICTS } from "@/lib/operator-overview"

const REFRESH_INTERVAL = 60_000

/** The list's filters a count can set: a sync status among people who may sign in, or disabled. */
export type HealthFilter = Pick<PeopleQuery, "verdict" | "state">

/**
 * Installation Health above everyone here: the installation's one verdict in a sentence, then how
 * many people are in each sync status and how many are disabled. It names nobody. Each count is a
 * shortcut that sets the list's Sync and State filters to show exactly those people, and reads as
 * pressed while the filters say the same, however they were set.
 */
export function InstallationHealthSummary({
  filters,
  now,
  onFilter,
}: {
  filters: HealthFilter
  now: number
  onFilter: (next: HealthFilter) => void
}) {
  const { t } = useI18n()
  const health = useQuery({
    queryKey: ["installation-health"],
    queryFn: api.installationHealth,
    refetchInterval: REFRESH_INTERVAL,
  })
  return (
    <section className="workflow page-card installation-health" aria-labelledby="installation-health-title">
      <h2 id="installation-health-title">{t("people.health.title")}</h2>
      {health.isPending && <Skeleton className="h-16 w-full" />}
      {health.error && (
        <div className="inline-error integration-load-error" role="alert">
          <span>{t("people.health.loadFailure")}</span>
          <Button type="button" variant="outline" onClick={() => void health.refetch()}>
            {t("people.health.tryAgain")}
          </Button>
        </div>
      )}
      {health.data && <HealthReport report={health.data} filters={filters} now={now} onFilter={onFilter} />}
    </section>
  )
}

function HealthReport({
  report,
  filters,
  now,
  onFilter,
}: {
  report: InstallationHealthReport
  filters: HealthFilter
  now: number
  onFilter: (next: HealthFilter) => void
}) {
  const i18n = useI18n()
  const { t } = i18n
  return (
    <>
      <HealthLead report={report} />
      {report.incidents.map((incident) => (
        <p key={incident.kind} className="user-overview-muted">
          {t("people.health.schedulerStalled", { relative: i18n.format.relative(incident.since, now) })}
        </p>
      ))}
      <Hints hints={report.hints} />
      <HealthCounts report={report} filters={filters} onFilter={onFilter} />
      <StatusMeanings />
    </>
  )
}

/** Likely causes from patterns across people, each with the guide's section on its fix. */
function Hints({ hints }: { hints: InstallationHint[] }) {
  const i18n = useI18n()
  if (hints.length === 0) return null
  return (
    <section className="installation-hints" aria-labelledby="installation-hints-title">
      <h3 id="installation-hints-title">{i18n.t("people.health.hints.title")}</h3>
      <ul>
        {hints.map((hint) => {
          const text = hintText(i18n, hint)
          return (
            <li key={`${hint.kind}:${hint.cause}`} className="installation-hint">
              <Lightbulb aria-hidden="true" />
              <div>
                <p>{text}</p>
                <HowToFixLink
                  href={troubleshootingUrl(hint.anchor)}
                  label={i18n.t("people.health.hints.howToFixLabel", { hint: text })}
                />
              </div>
            </li>
          )
        })}
      </ul>
    </section>
  )
}

/**
 * What the administrator must do, first. A stalled scheduler, or a likely cause only they can fix,
 * needs them; people's own problems do not, so they are one quiet line: each person sees their
 * own step on their dashboard, and the administrator finds it on their page if they ask.
 */
function HealthLead({ report }: { report: InstallationHealthReport }) {
  const i18n = useI18n()
  const { t } = i18n
  if (report.status === "stalled") {
    return (
      <div className="user-overview-verdict installation-health-lead">
        <VerdictBadge verdict={report.status} />
        <p>{t("people.health.summary.stalled")}</p>
      </div>
    )
  }
  if (report.hints.length > 0) {
    return (
      <div className="user-overview-verdict installation-health-lead">
        <Badge variant="stopped">
          <ShieldAlert aria-hidden="true" />
          {t("people.health.needsYou")}
        </Badge>
        <p>{t("people.health.needsYouDetail")}</p>
      </div>
    )
  }
  return (
    <div className="user-overview-verdict installation-health-lead">
      <Badge variant="healthy">
        <CheckCircle2 aria-hidden="true" />
        {t("people.health.nothingNeedsYou")}
      </Badge>
      <p>{quietSentence(i18n, report)}</p>
    </div>
  )
}

/** Verdicts that mean a person has something to do, or to wait for, on their own dashboard. */
const OWN_TROUBLE = ["stopped", "review", "waiting"] as const

/** With nothing for the administrator to do: how many people have something of their own. */
function quietSentence(i18n: I18n, report: InstallationHealthReport): string {
  const total = Object.values(report.users).reduce((sum, count) => sum + count, 0)
  const count = OWN_TROUBLE.reduce((sum, verdict) => sum + (report.users[verdict] ?? 0), 0)
  if (count > 0) return i18n.t("people.health.ownFixes", { count, total })
  if (report.status === "paused" || report.status === "setup") return i18n.t(`people.health.summary.${report.status}`)
  return i18n.t("people.health.summary.healthy", { count: total })
}

function HealthCounts({
  report,
  filters,
  onFilter,
}: {
  report: InstallationHealthReport
  filters: HealthFilter
  onFilter: (next: HealthFilter) => void
}) {
  const { t } = useI18n()
  const counted = VERDICTS.filter((each) => (report.users[each] ?? 0) > 0)
  const everyone: HealthFilter = { verdict: "", state: "" }
  const showingDisabled = filters.state === "disabled" && filters.verdict === ""
  if (counted.length === 0 && report.disabled_users === 0) return null
  return (
    <div className="installation-health-counts" role="group" aria-labelledby="health-counts-label">
      <span id="health-counts-label" className="health-counts-label">
        {t("people.health.countsLabel")}
      </span>
      {counted.map((each) => {
        const pressed = filters.verdict === each && filters.state === "active"
        return (
          <Button
            key={each}
            type="button"
            variant="outline"
            className="health-count"
            aria-pressed={pressed}
            onClick={() => onFilter(pressed ? everyone : { verdict: each, state: "active" })}
          >
            <VerdictIcon verdict={each} />
            {t("people.health.count", { verdict: t(`people.verdicts.${each}`), count: report.users[each] ?? 0 })}
          </Button>
        )
      })}
      {report.disabled_users > 0 && (
        <Button
          type="button"
          variant="outline"
          className="health-count"
          aria-pressed={showingDisabled}
          onClick={() => onFilter(showingDisabled ? everyone : { verdict: "", state: "disabled" })}
        >
          <UserX aria-hidden="true" />
          {t("people.health.count", { verdict: t("people.states.disabled"), count: report.disabled_users })}
        </Button>
      )}
    </div>
  )
}

/** What each sync status means, one line each, for anyone who has to ask. */
function StatusMeanings() {
  const { t } = useI18n()
  return (
    <details className="inline-help status-meanings">
      <summary>
        <CircleHelp aria-hidden="true" />
        <span>{t("people.health.meanings")}</span>
        <ChevronDown className="inline-help-chevron" aria-hidden="true" />
      </summary>
      <dl className="inline-help-body">
        {VERDICTS.map((verdict) => (
          <div key={verdict}>
            <dt>
              <VerdictBadge verdict={verdict} />
            </dt>
            <dd>{t(`people.overview.verdict.${verdict}`)}</dd>
          </div>
        ))}
      </dl>
    </details>
  )
}
