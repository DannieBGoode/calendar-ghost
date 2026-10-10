import { useQuery } from "@tanstack/react-query"
import { useEffect, useRef } from "react"
import { ArrowLeft } from "lucide-react"

import { GhostMark } from "@/components/ghost-mark"
import { LoadFailure } from "@/components/load-failure"
import { PageSkeleton } from "@/components/page-skeleton"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { DisabledBadge } from "@/components/verdict-badge"
import { PersonDetails, PersonMenu } from "@/features/person-actions"
import { UserOverviewDetails, type OwnPage } from "@/features/user-overview"
import { useI18n } from "@/i18n/provider"
import { api, ApiError, type Person, type RuleSummary, type UserOverview } from "@/lib/api"
import { documentTitle } from "@/lib/brand"
import { appPathForView, isPlainLeftClick } from "@/lib/navigation"
import { AS_ADMINISTRATOR } from "@/lib/operator-overview"
import { isAdministrator, personName } from "@/lib/people"
import { useNow } from "@/lib/use-now"
import { peopleReturnSearch, usePersonCommands } from "@/lib/use-people"

/**
 * One person under People, for an Installation Administrator: who they are, what the Operator
 * Overview shows about them, which they also see in their own Settings, and the same actions as
 * their row. Their calendars, Google accounts, and events are never shown.
 */
export function PersonView({
  personId,
  onBack,
  onDeleted,
  own,
}: {
  personId: string
  onBack: () => void
  onDeleted: (notice: string) => void
  /** Where the administrator goes for their own steps, on their own page. */
  own: OwnSteps
}) {
  const { t } = useI18n()
  const session = useQuery({ queryKey: ["session"], queryFn: api.session })
  // Under People's key, so every person command refreshes it with the list.
  const overview = useQuery({ queryKey: ["people", "overview", personId], queryFn: () => api.personOverview(personId) })

  if (overview.isPending || session.isPending) return <PageSkeleton label={t("people.person.loading")} />
  if (overview.error instanceof ApiError && overview.error.status === 404) return <MissingPerson onBack={onBack} />
  if (!overview.data) {
    return <LoadFailure title={t("people.person.loadFailure")} onRetry={() => void overview.refetch()} />
  }
  return (
    <PersonContent
      overview={overview.data}
      you={overview.data.user.id === session.data?.user?.id ? own : null}
      onBack={onBack}
      onDeleted={onDeleted}
    />
  )
}

function PersonContent({
  overview,
  you,
  onBack,
  onDeleted,
}: {
  overview: UserOverview
  /** The administrator's own steps when this is their own page; null for anyone else's. */
  you: OwnSteps | null
  onBack: () => void
  onDeleted: (notice: string) => void
}) {
  const i18n = useI18n()
  const { t } = i18n
  const now = useNow()
  const commands = usePersonCommands({ onDeleted })
  const person = overview.user
  const name = personName(i18n, person)
  const heading = useRef<HTMLHeadingElement>(null)
  // A person's page is a page of its own: it starts at their name, and the tab says whose it is.
  useEffect(() => {
    heading.current?.focus({ preventScroll: true })
  }, [])
  useEffect(() => {
    document.title = documentTitle(i18n, t("people.person.documentTitle", { name }))
  }, [i18n, t, name])
  return (
    <div className="page-section person-page">
      <BackToPeople href={`${appPathForView("people")}${peopleReturnSearch(person.id)}`} onBack={onBack} />
      <div className="person-heading">
        <div>
          <h1 ref={heading} tabIndex={-1}>
            {name}
            {you !== null && <Badge variant="outline">{t("people.you")}</Badge>}
            {person.state === "disabled" && <DisabledBadge />}
          </h1>
          <PersonFacts person={person} now={now} />
        </div>
        {you === null && <PersonMenu person={person} name={name} commands={commands} />}
      </div>
      {you === null && <PersonDetails person={person} name={name} commands={commands} />}
      <p className="sr-only" role="status">
        {commands.message}
      </p>
      {you ? (
        <OwnOverview overview={overview} now={now} steps={you} />
      ) : (
        <UserOverviewDetails overview={overview} now={now} audience={{ name }} />
      )}
      {/* What administrators never see is about someone else; on their own page it says nothing. */}
      {you === null && <p className="page-footnote">{t("people.person.intro")}</p>}
    </div>
  )
}

/** Where an administrator's own steps lead from their own page. */
export type OwnSteps = Omit<OwnPage, "names">

/**
 * An administrator's own page. Only administrators see People, so they read the steps as their
 * own, with links to take them, and their calendars by the names they gave them.
 */
function OwnOverview({ overview, now, steps }: { overview: UserOverview; now: number; steps: OwnSteps }) {
  const rules = useQuery({ queryKey: ["rules"], queryFn: api.rules })
  const own: OwnPage = { ...steps, names: ownCalendarNames(overview, rules.data ?? []) }
  return <UserOverviewDetails overview={overview} now={now} audience={AS_ADMINISTRATOR} own={own} />
}

/** Each number's calendar, by the administrator's own name for it, from their own rules. */
function ownCalendarNames(overview: UserOverview, rules: RuleSummary[]): Map<number, string> {
  const mine = new Map(rules.map((rule) => [rule.id, rule]))
  const names = new Map<number, string>()
  for (const rule of overview.status.rules) {
    const own = mine.get(rule.id)
    if (!own) continue
    for (const [shown, endpoint] of [
      [rule.source, own.source],
      [rule.destination, own.destination],
    ] as const) {
      if (typeof shown.number === "number" && !names.has(shown.number)) {
        names.set(shown.number, endpoint.calendar_name ?? endpoint.calendar_id)
      }
    }
  }
  return names
}

/** Back to People as it was when this person was opened: the same search, filters, and page. */
function BackToPeople({ href, onBack }: { href: string; onBack: () => void }) {
  const { t } = useI18n()
  return (
    <a
      className="person-back text-link"
      href={href}
      onClick={(event) => {
        if (!isPlainLeftClick(event)) return
        event.preventDefault()
        onBack()
      }}
    >
      <ArrowLeft aria-hidden="true" />
      {t("people.person.back")}
    </a>
  )
}

/** Their role, and when they joined and last signed in. */
function PersonFacts({ person, now }: { person: Person; now: number }) {
  const i18n = useI18n()
  const { t } = i18n
  const facts = [
    t(`people.roles.${person.role}`),
    t("people.person.joined", { relative: i18n.format.relative(person.created_at, now) }),
    person.last_sign_in_at
      ? t("people.person.lastSignIn", { relative: i18n.format.relative(person.last_sign_in_at, now) })
      : t("people.person.neverSignedIn"),
  ]
  return (
    <ul className="person-facts" data-administrator={isAdministrator(person)}>
      {facts.map((fact) => (
        <li key={fact}>{fact}</li>
      ))}
    </ul>
  )
}

/** An address naming nobody here, such as someone deleted since the link was copied. */
function MissingPerson({ onBack }: { onBack: () => void }) {
  const { t } = useI18n()
  return (
    <div className="page-section">
      <div className="empty-panel">
        <GhostMark className="empty-ghost" />
        <h1>{t("people.person.missing.title")}</h1>
        <p>{t("people.person.missing.body")}</p>
        <div className="empty-actions">
          <Button variant="outline" onClick={onBack}>
            {t("people.person.missing.back")}
          </Button>
        </div>
      </div>
    </div>
  )
}
