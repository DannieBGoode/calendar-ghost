import { useQuery } from "@tanstack/react-query"

import { GhostMark } from "@/components/ghost-mark"
import { LoadFailure } from "@/components/load-failure"
import { PageSkeleton } from "@/components/page-skeleton"
import { Button } from "@/components/ui/button"
import { PeopleFilters } from "@/features/people-filters"
import { InvitationsSection } from "@/features/people-invitations"
import { PeoplePagination } from "@/features/people-pagination"
import { PeopleTable } from "@/features/people-table"
import { useI18n } from "@/i18n/provider"
import { api, type PeoplePage, type PeopleQuery, type PeopleSort } from "@/lib/api"
import { DEFAULT_PEOPLE_QUERY, nextSort } from "@/lib/people-query"
import { useNow } from "@/lib/use-now"
import { usePeopleAccess } from "@/lib/use-people-access"
import { usePeopleLocation, type UpdatePeopleQuery } from "@/lib/use-people-location"
import { usePeoplePage, usePersonCommands, type PeopleCommands } from "@/lib/use-people"

/**
 * The people who use this installation, for an Installation Administrator: who they are, their
 * role and state, and when they last signed in, never what they own. Invitations sit above them.
 * The app offers this page only while the Registration Policy lets people join.
 */
export function PeopleView() {
  const { t } = useI18n()
  const access = usePeopleAccess()
  const session = useQuery({ queryKey: ["session"], queryFn: api.session })
  const user = session.data?.user
  if (access !== "open" || !user) return <PageSkeleton label={t("people.page.loading")} />
  return <PeopleContent currentUserId={user.id} />
}

function PeopleContent({ currentUserId }: { currentUserId: string }) {
  const { t } = useI18n()
  const [query, update] = usePeopleLocation()
  const people = usePeoplePage(query)
  const commands = usePersonCommands()
  const now = useNow()

  if (people.isPending) return <PageSkeleton label={t("people.page.loading")} />
  // A failed refresh keeps the page already shown; only a page that never arrived is a failure.
  if (!people.data) {
    return <LoadFailure title={t("people.page.loadFailure")} onRetry={() => void people.refetch()} />
  }

  return (
    <div className="page-section people-page">
      <div>
        <h1>{t("people.page.title")}</h1>
        <p className="page-intro">{t("people.page.intro")}</p>
      </div>
      <InvitationsSection now={now} />
      <section className="settings-section" aria-labelledby="people-list-title">
        <div className="section-heading">
          <h2 id="people-list-title" className="people-list-title" tabIndex={-1}>
            {t("people.page.listTitle")}
          </h2>
        </div>
        <PeopleFilters query={query} onChange={(next) => update({ ...next, page: 1 }, "replace")} />
        <p className="sr-only" role="status">
          {people.isPlaceholderData ? t("people.pagination.updating") : ""}
        </p>
        <PeopleResults
          page={people.data}
          query={query}
          updating={people.isPlaceholderData}
          currentUserId={currentUserId}
          now={now}
          commands={commands}
          update={update}
        />
        {commands.message && <p role="status">{commands.message}</p>}
      </section>
    </div>
  )
}

function PeopleResults({
  page,
  query,
  updating,
  currentUserId,
  now,
  commands,
  update,
}: {
  page: PeoplePage
  query: PeopleQuery
  updating: boolean
  currentUserId: string
  now: number
  commands: PeopleCommands
  update: UpdatePeopleQuery
}) {
  function openPage(next: number) {
    update({ page: next }, "push")
    // The new page starts at the list's heading, as a new page of the app starts at its own.
    const heading = document.getElementById("people-list-title")
    heading?.focus({ preventScroll: true })
    heading?.scrollIntoView({ block: "start" })
  }

  if (page.users.length === 0) {
    return page.total === 0 ? (
      <EmptyPeople kind="empty" onAction={() => update(DEFAULT_PEOPLE_QUERY, "replace")} />
    ) : (
      <EmptyPeople kind="beyond" onAction={() => update({ page: 1 }, "replace")} />
    )
  }
  return (
    <div className="people-table-wrap" aria-busy={updating} data-updating={updating}>
      <PeopleTable
        people={page.users}
        query={query}
        currentUserId={currentUserId}
        now={now}
        commands={commands}
        onSort={(sort: PeopleSort) => update(nextSort(query, sort), "replace")}
      />
      <PeoplePagination page={page} onPage={openPage} />
    </div>
  )
}

/** Nobody matches the search and filters, or a linked page lies past the last one. */
function EmptyPeople({ kind, onAction }: { kind: "empty" | "beyond"; onAction: () => void }) {
  const { t } = useI18n()
  return (
    <div className="empty-panel">
      <GhostMark className="empty-ghost" />
      <h2>{t(`people.${kind}.title`)}</h2>
      <p>{t(`people.${kind}.body`)}</p>
      <div className="empty-actions">
        <Button variant="outline" onClick={onAction}>
          {t(kind === "empty" ? "people.empty.clear" : "people.beyond.first")}
        </Button>
      </div>
    </div>
  )
}
