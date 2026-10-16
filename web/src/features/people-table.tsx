import { ArrowDown, ArrowUp, ArrowUpDown, TriangleAlert } from "lucide-react"
import { Fragment, useEffect, useRef } from "react"

import { Badge } from "@/components/ui/badge"
import { DisabledBadge, VerdictBadge } from "@/components/verdict-badge"
import { PersonDetails, PersonMenu } from "@/features/person-actions"
import { useI18n } from "@/i18n/provider"
import type { MessageKey } from "@/i18n/types"
import type { PeopleQuery, PeopleSort, PersonRow, SortOrder } from "@/lib/api"
import { appPathForPerson, isPlainLeftClick, type OpenPerson } from "@/lib/navigation"
import { isAdministrator, lastSignIn, personName } from "@/lib/people"
import { personPlanOver, personPlanText } from "@/lib/plans"
import { rememberOpenedPerson, takeOpenedPerson, type PeopleCommands } from "@/lib/use-people"

// Fixed widths, so columns stay put whatever a filter shows; Plan only once a Plan exists.
const COLUMN_CLASSES = ["col-email", "col-sync", "col-role", "col-state", "col-joined", "col-last", "col-actions"]
const PLAN_COLUMN_CLASSES = ["col-email", "col-sync", "col-role", "col-state", "col-plan", "col-joined", "col-last", "col-actions"]
const ARIA_SORT: Record<SortOrder, "ascending" | "descending"> = { asc: "ascending", desc: "descending" }
const SORT_ICONS = { asc: ArrowUp, desc: ArrowDown }

/**
 * One page of people as a table. Email, Sync, Joined, and Last sign-in sort when their heading is
 * pressed; each email opens that person's page. Once a Plan exists, each person's Plan has a
 * column, in the words of their page. On a narrow screen each row becomes a card that labels its
 * own values, and the sortable headings stay above the cards as buttons.
 */
export function PeopleTable({
  people,
  query,
  currentUserId,
  now,
  commands,
  onSort,
  onOpenPerson,
}: {
  people: PersonRow[]
  query: PeopleQuery
  currentUserId: string
  now: number
  commands: PeopleCommands
  onSort: (sort: PeopleSort) => void
  onOpenPerson: OpenPerson
}) {
  const { t } = useI18n()
  const table = useRef<HTMLTableElement>(null)
  // Coming back from a person's page starts at that person's row.
  useEffect(() => {
    const personId = takeOpenedPerson()
    if (personId === null) return
    table.current?.querySelector<HTMLAnchorElement>(`a[href="${appPathForPerson(personId)}"]`)?.focus()
  }, [])
  const sortable = (column: PeopleSort, label: MessageKey) => (
    <SortHeader column={column} label={t(label)} query={query} onSort={onSort} />
  )
  // The Operator Overview gives everyone a Plan once any Plan exists, and nobody before.
  const planned = people.some((person) => person.plan !== null)
  const columns = planned ? PLAN_COLUMN_CLASSES : COLUMN_CLASSES
  return (
    <table ref={table} className="people-table" role="table" aria-labelledby="people-list-title" data-plans={planned}>
      <colgroup>
        {columns.map((name) => (
          <col key={name} className={name} />
        ))}
      </colgroup>
      <thead role="rowgroup">
        <tr role="row">
          {sortable("email", "people.table.email")}
          {sortable("verdict", "people.table.sync")}
          <th scope="col" role="columnheader">{t("people.table.role")}</th>
          <th scope="col" role="columnheader">{t("people.table.state")}</th>
          {planned && <th scope="col" role="columnheader">{t("people.table.plan")}</th>}
          {sortable("joined", "people.table.joined")}
          {sortable("last_sign_in", "people.table.lastSignIn")}
          <th scope="col" role="columnheader">
            <span className="sr-only">{t("people.table.actions")}</span>
          </th>
        </tr>
      </thead>
      <tbody role="rowgroup">
        {people.map((person) => (
          <PersonRows
            key={person.id}
            person={person}
            you={person.id === currentUserId}
            planned={planned}
            columns={columns.length}
            now={now}
            commands={commands}
            onOpen={onOpenPerson}
          />
        ))}
      </tbody>
    </table>
  )
}

function SortHeader({
  column,
  label,
  query,
  onSort,
}: {
  column: PeopleSort
  label: string
  query: PeopleQuery
  onSort: (sort: PeopleSort) => void
}) {
  const active = query.sort === column
  const Icon = active ? SORT_ICONS[query.order] : ArrowUpDown
  return (
    <th scope="col" role="columnheader" data-sortable="true" aria-sort={active ? ARIA_SORT[query.order] : undefined}>
      <button type="button" className="sort-button" data-active={active} onClick={() => onSort(column)}>
        {label}
        <Icon aria-hidden="true" />
      </button>
    </th>
  )
}

/**
 * A person's Plan, as their page says it after "Plan:". A limit they have more of than it allows
 * takes Attention Ochre and the attention icon beside the words that say so, never the tone alone.
 */
function PlanCell({ person }: { person: PersonRow }) {
  const i18n = useI18n()
  const administrator = isAdministrator(person)
  const over = person.plan !== null && personPlanOver(person.plan, administrator)
  return (
    <td
      role="cell"
      className="person-col-plan"
      data-label={i18n.t("people.table.plan")}
      data-tone={over ? "attention" : undefined}
    >
      {over && <TriangleAlert aria-hidden="true" />}
      {person.plan && personPlanText(i18n, person.plan, administrator)}
    </td>
  )
}

function PersonRows({
  person,
  you,
  planned,
  columns,
  now,
  commands,
  onOpen,
}: {
  person: PersonRow
  you: boolean
  /** A Plan exists, so the row has a Plan column. */
  planned: boolean
  /** How many columns the table has, which a row of details spans. */
  columns: number
  now: number
  commands: PeopleCommands
  onOpen: OpenPerson
}) {
  const i18n = useI18n()
  const { t } = i18n
  const name = personName(i18n, person)
  return (
    <Fragment>
      <tr role="row" className="person-row">
        <td role="cell" className="person-col-email">
          <a
            className="person-email"
            data-missing={person.email === null}
            href={appPathForPerson(person.id)}
            onClick={(event) => {
              if (!isPlainLeftClick(event)) return
              event.preventDefault()
              rememberOpenedPerson(person.id, window.location.search)
              onOpen(person.id)
            }}
          >
            {name}
          </a>
          {you && <Badge variant="outline">{t("people.you")}</Badge>}
        </td>
        <td role="cell" className="person-col-sync" data-label={t("people.table.sync")}>
          <VerdictBadge verdict={person.verdict} />
          {person.problems > 0 && (
            <span className="person-problems">{t("people.problems", { count: person.problems })}</span>
          )}
        </td>
        <td role="cell" className="person-col-role" data-label={t("people.table.role")}>
          {t(`people.roles.${person.role}`)}
        </td>
        <td role="cell" className="person-col-state" data-label={t("people.table.state")}>
          {person.state === "disabled" ? <DisabledBadge /> : t("people.states.active")}
        </td>
        {planned && <PlanCell person={person} />}
        <td role="cell" className="person-col-joined" data-label={t("people.table.joined")}>
          <time dateTime={person.created_at} title={i18n.format.dateTime(person.created_at)}>
            {i18n.format.relative(person.created_at, now)}
          </time>
        </td>
        <td role="cell" className="person-col-last" data-label={t("people.table.lastSignIn")}>
          {person.last_sign_in_at ? (
            <time dateTime={person.last_sign_in_at} title={i18n.format.dateTime(person.last_sign_in_at)}>
              {lastSignIn(i18n, person, now)}
            </time>
          ) : (
            lastSignIn(i18n, person, now)
          )}
        </td>
        <td role="cell" className="person-col-actions">
          {!you && <PersonMenu person={person} name={name} commands={commands} />}
        </td>
      </tr>
      {commands.hasDetails(person) && (
        <tr role="row" className="person-details-row">
          <td role="cell" colSpan={columns}>
            <PersonDetails person={person} name={name} commands={commands} />
          </td>
        </tr>
      )}
    </Fragment>
  )
}
