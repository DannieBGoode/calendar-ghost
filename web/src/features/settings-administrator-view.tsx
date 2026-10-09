import { useQuery } from "@tanstack/react-query"
import { useRef, useState, type RefObject } from "react"

import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { VerdictBadge } from "@/components/verdict-badge"
import { UserOverviewDetails } from "@/features/user-overview"
import { useI18n } from "@/i18n/provider"
import { api, type RuleSummary, type UserOverview } from "@/lib/api"
import { THEMSELF } from "@/lib/operator-overview"
import { useDisclosureFocus } from "@/lib/use-disclosure-focus"
import { useNow } from "@/lib/use-now"
import { useOverviewSharing } from "@/lib/use-people-access"

/**
 * What the Operator Overview shows Installation Administrators about the signed-in User, from the
 * same answer they read, collapsed to one row until asked for. Under Only me nobody else is here,
 * so it is not shown.
 */
export function AdministratorViewSection() {
  const sharing = useOverviewSharing()
  if (sharing !== "shared") return null
  return <AdministratorView />
}

function AdministratorView() {
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
              <div>
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
      {overview.data && open && <AdministratorViewDetails overview={overview.data} focusTarget={details} />}
    </section>
  )
}

function AdministratorViewDetails({
  overview,
  focusTarget,
}: {
  overview: UserOverview
  focusTarget: RefObject<HTMLDivElement | null>
}) {
  const now = useNow()
  return (
    <div id="administrator-view-details" ref={focusTarget} tabIndex={-1} className="administrator-view-details">
      <CalendarKey overview={overview} />
      <UserOverviewDetails overview={overview} now={now} audience={THEMSELF} headingLevel={3} />
    </div>
  )
}

/** Which of the User's own calendars each number stands for; only they see the names. */
function CalendarKey({ overview }: { overview: UserOverview }) {
  const { t } = useI18n()
  const rules = useQuery({ queryKey: ["rules"], queryFn: api.rules })
  const key = calendarKey(overview, rules.data ?? [])
  if (key.length === 0) return null
  return (
    <div className="calendar-key">
      <p>{t("settings.administratorView.keyTitle")}</p>
      <ul>
        {key.map(({ number, name }) => (
          <li key={number}>{t("settings.administratorView.keyItem", { number, name })}</li>
        ))}
      </ul>
    </div>
  )
}

function calendarKey(overview: UserOverview, rules: RuleSummary[]): { number: number; name: string }[] {
  const own = new Map(rules.map((rule) => [rule.id, rule]))
  const names = new Map<number, string>()
  for (const rule of overview.status.rules) {
    const mine = own.get(rule.id)
    if (!mine) continue
    for (const [shown, endpoint] of [
      [rule.source, mine.source],
      [rule.destination, mine.destination],
    ] as const) {
      if (shown.number !== null && !names.has(shown.number)) {
        names.set(shown.number, endpoint.calendar_name ?? endpoint.calendar_id)
      }
    }
  }
  return [...names].sort(([a], [b]) => a - b).map(([number, name]) => ({ number, name }))
}
