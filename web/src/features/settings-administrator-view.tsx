import { useQuery } from "@tanstack/react-query"
import { useRef, useState } from "react"

import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { VerdictBadge } from "@/components/verdict-badge"
import { ROWS, UserOverviewDetails, type OwnActions } from "@/features/user-overview"
import { useI18n } from "@/i18n/provider"
import { api, type RuleSummary, type UserOverview } from "@/lib/api"
import { THEMSELF } from "@/lib/operator-overview"
import { useDisclosureFocus } from "@/lib/use-disclosure-focus"
import { useNow } from "@/lib/use-now"
import { useOverviewSharing } from "@/lib/use-people-access"

/**
 * What the Operator Overview shows Installation Administrators about the signed-in User, from the
 * same answer they read, collapsed to one row until asked for. The User also sees their own
 * calendar names beside each number, which administrators never do. Under Only me nobody else is
 * here, so it is not shown.
 */
export function AdministratorViewSection({ actions }: { actions: OwnActions }) {
  const sharing = useOverviewSharing()
  if (sharing !== "shared") return null
  return <AdministratorView actions={actions} />
}

function AdministratorView({ actions }: { actions: OwnActions }) {
  const { t } = useI18n()
  const overview = useQuery({ queryKey: ["own-overview"], queryFn: api.ownOverview })
  const [open, setOpen] = useState(false)
  const toggle = useRef<HTMLButtonElement>(null)
  const details = useRef<HTMLDivElement>(null)
  useDisclosureFocus(open, details, toggle)
  return (
    <section className="settings-section" aria-labelledby="administrator-view-title">
      <div className="section-heading">
        <div>
          <h2 id="administrator-view-title">{t("settings.administratorView.title")}</h2>
          <p>{t("settings.administratorView.intro")}</p>
        </div>
      </div>
      {overview.isPending && <Skeleton className="h-16 w-full" />}
      {overview.error && (
        <div className="inline-error integration-load-error" role="alert">
          <span>{t("settings.administratorView.loadFailure")}</span>
          <Button type="button" variant="outline" onClick={() => void overview.refetch()}>
            {t("settings.administratorView.tryAgain")}
          </Button>
        </div>
      )}
      {overview.data && (
        <div className="settings-list">
          <div className="setting-item">
            <div className="setting-row">
              <div className="administrator-view-summary">
                <h3>{t("settings.administratorView.summary")}</h3>
                <VerdictBadge verdict={overview.data.status.status} />
              </div>
              <Button
                ref={toggle}
                type="button"
                variant="outline"
                aria-expanded={open}
                aria-controls={open ? "administrator-view-details" : undefined}
                onClick={() => setOpen(!open)}
              >
                {t(open ? "settings.administratorView.hide" : "settings.administratorView.show")}
              </Button>
            </div>
          </div>
        </div>
      )}
      {overview.data && open && (
        <div
          id="administrator-view-details"
          ref={details}
          tabIndex={-1}
          role="group"
          aria-label={t("settings.administratorView.detailsLabel")}
          className="administrator-view-details"
        >
          <OwnOverview overview={overview.data} actions={actions} />
        </div>
      )}
    </section>
  )
}

function OwnOverview({ overview, actions }: { overview: UserOverview; actions: OwnActions }) {
  const now = useNow()
  const rules = useQuery({ queryKey: ["rules"], queryFn: api.rules })
  return (
    <UserOverviewDetails
      overview={overview}
      now={now}
      audience={THEMSELF}
      headingLevel={3}
      layout={ROWS}
      ownNames={ownCalendarNames(overview, rules.data ?? [])}
      actions={actions}
    />
  )
}

/** Each number's calendar, by the User's own name for it, from their own rules. */
function ownCalendarNames(overview: UserOverview, rules: RuleSummary[]): Map<number, string> {
  const own = new Map(rules.map((rule) => [rule.id, rule]))
  const names = new Map<number, string>()
  for (const rule of overview.status.rules) {
    const mine = own.get(rule.id)
    if (!mine) continue
    for (const [shown, endpoint] of [
      [rule.source, mine.source],
      [rule.destination, mine.destination],
    ] as const) {
      if (typeof shown.number === "number" && !names.has(shown.number)) {
        names.set(shown.number, endpoint.calendar_name ?? endpoint.calendar_id)
      }
    }
  }
  return names
}
