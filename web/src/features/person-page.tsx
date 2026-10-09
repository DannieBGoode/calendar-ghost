import { useQuery } from "@tanstack/react-query"
import { ArrowLeft } from "lucide-react"

import { GhostMark } from "@/components/ghost-mark"
import { LoadFailure } from "@/components/load-failure"
import { PageSkeleton } from "@/components/page-skeleton"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { PersonDetails, PersonMenu } from "@/features/person-actions"
import { UserOverviewDetails } from "@/features/user-overview"
import { useI18n } from "@/i18n/provider"
import { api, ApiError, type Person, type UserOverview } from "@/lib/api"
import { appPathForView, isPlainLeftClick } from "@/lib/navigation"
import { isAdministrator, personName } from "@/lib/people"
import { useNow } from "@/lib/use-now"
import { usePersonCommands } from "@/lib/use-people"

/**
 * One person under People, for an Installation Administrator: who they are, what the Operator
 * Overview shows about them, which they also see in their own Settings, and the same actions as
 * their row. Their calendars, Google accounts, and events are never shown.
 */
export function PersonView({
  personId,
  onBack,
  onDeleted,
}: {
  personId: string
  onBack: () => void
  onDeleted: (notice: string) => void
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
      you={overview.data.user.id === session.data?.user?.id}
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
  you: boolean
  onBack: () => void
  onDeleted: (notice: string) => void
}) {
  const i18n = useI18n()
  const { t } = i18n
  const commands = usePersonCommands({ onDeleted })
  const person = overview.user
  const name = personName(i18n, person)
  return (
    <div className="page-section person-page">
      <BackToPeople onBack={onBack} />
      <div className="person-heading">
        <div>
          <h1>
            {name}
            {you && <Badge variant="outline">{t("people.you")}</Badge>}
          </h1>
          <PersonFacts person={person} />
        </div>
        {!you && <PersonMenu person={person} name={name} commands={commands} />}
      </div>
      {!you && <PersonDetails person={person} name={name} commands={commands} />}
      {commands.message && <p role="status">{commands.message}</p>}
      <p className="page-intro">{t("people.person.intro")}</p>
      <UserOverviewDetails overview={overview} headingLevel={2} />
    </div>
  )
}

function BackToPeople({ onBack }: { onBack: () => void }) {
  const { t } = useI18n()
  return (
    <a
      className="person-back text-link"
      href={appPathForView("people")}
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

/** Their role and state, and when they joined and last signed in. */
function PersonFacts({ person }: { person: Person }) {
  const i18n = useI18n()
  const { t } = i18n
  const now = useNow()
  const facts = [
    t(`people.roles.${person.role}`),
    t(`people.states.${person.state}`),
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
