import { GhostMark } from "@/components/ghost-mark"
import { LoadFailure } from "@/components/load-failure"
import { Skeleton } from "@/components/ui/skeleton"
import { Button } from "@/components/ui/button"
import { PeopleFilters } from "@/features/people-filters"
import { InstallationHealthSummary } from "@/features/people-health"
import { PeoplePagination } from "@/features/people-pagination"
import { PeopleTable } from "@/features/people-table"
import { useI18n } from "@/i18n/provider"
import type { I18n } from "@/i18n/translator"
import type { PeoplePage, PeopleQuery, PeopleSort, Verdict } from "@/lib/api"
import type { OpenPerson } from "@/lib/navigation"
import { DEFAULT_PEOPLE_QUERY, nextSort, pageRange } from "@/lib/people-query"
import { usePeoplePage, usePersonCommands, type PeopleCommands } from "@/lib/use-people"
import type { UpdatePeopleQuery } from "@/lib/use-people-location"

/**
 * People's first tab: Installation Health, then everyone here in one card with its search,
 * filters, table, and pages. Health and invitations load beside the list, not after it.
 */
export function PeopleRoster({
  query,
  update,
  currentUserId,
  now,
  notice,
  onOpenPerson,
}: {
  query: PeopleQuery
  update: UpdatePeopleQuery
  currentUserId: string
  now: number
  notice: string | null
  onOpenPerson: OpenPerson
}) {
  const i18n = useI18n()
  const { t } = i18n
  const people = usePeoplePage(query)
  const commands = usePersonCommands()

  // A count counts people who may sign in, so it shows exactly those people.
  function showVerdict(verdict: Verdict | "") {
    update({ verdict, state: verdict ? "active" : "", page: 1 }, "replace")
  }

  return (
    <>
      <InstallationHealthSummary verdict={query.state === "active" ? query.verdict : ""} now={now} onFilter={showVerdict} />
      <section className="workflow page-card people-roster" aria-labelledby="people-list-title">
        <div className="section-heading">
          <h2 id="people-list-title" className="people-list-title" tabIndex={-1}>
            {t("people.page.listTitle")}
          </h2>
        </div>
        <PeopleFilters query={query} onChange={(next) => update({ ...next, page: 1 }, "replace")} />
        <p className="sr-only" role="status">
          {resultsStatus(i18n, people.data, people.isPlaceholderData)}
        </p>
        {people.isPending && <Skeleton className="h-40 w-full" />}
        {!people.isPending && !people.data && (
          <LoadFailure title={t("people.page.loadFailure")} onRetry={() => void people.refetch()} />
        )}
        {people.data && (
          <PeopleResults
            page={people.data}
            query={query}
            updating={people.isPlaceholderData}
            currentUserId={currentUserId}
            now={now}
            commands={commands}
            update={update}
            onOpenPerson={onOpenPerson}
          />
        )}
        {/* A deletion's result has no row left to sit on. */}
        {(commands.deletedMessage || notice) && (
          <p className="command-result">{commands.deletedMessage || notice}</p>
        )}
        <p className="sr-only people-command-status" role="status">
          {commands.message}
        </p>
      </section>
    </>
  )
}

/** Who the list shows now, said once each search, filter, sort, or page arrives. */
function resultsStatus(i18n: I18n, page: PeoplePage | undefined, updating: boolean): string {
  if (updating) return i18n.t("people.pagination.updating")
  if (!page) return ""
  if (page.users.length === 0) return i18n.t("people.empty.title")
  const range = pageRange({ ...page, shown: page.users.length })
  return i18n.t("people.pagination.summary", { first: range.first, last: range.last, count: page.total })
}

function PeopleResults({
  page,
  query,
  updating,
  currentUserId,
  now,
  commands,
  update,
  onOpenPerson,
}: {
  page: PeoplePage
  query: PeopleQuery
  updating: boolean
  currentUserId: string
  now: number
  commands: PeopleCommands
  update: UpdatePeopleQuery
  onOpenPerson: OpenPerson
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
        onOpenPerson={onOpenPerson}
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
      <h3>{t(`people.${kind}.title`)}</h3>
      <p>{t(`people.${kind}.body`)}</p>
      <div className="empty-actions">
        <Button variant="outline" onClick={onAction}>
          {t(kind === "empty" ? "people.empty.clear" : "people.beyond.first")}
        </Button>
      </div>
    </div>
  )
}
