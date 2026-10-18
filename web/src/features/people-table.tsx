import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react"
import { Fragment, useEffect, useRef } from "react"

import { PlanChips } from "@/components/plan-chips"
import { Badge } from "@/components/ui/badge"
import { Checkbox } from "@/components/ui/checkbox"
import { DisabledBadge, VerdictBadge } from "@/components/verdict-badge"
import { SELECT_ALL } from "@/features/people-bulk-bar"
import { PersonDetails, PersonMenu } from "@/features/person-actions"
import { LIST_TITLE, RowPlanPopover } from "@/features/plan-change-popover"
import type { PlanChanges } from "@/features/use-plan-changes"
import { useI18n } from "@/i18n/provider"
import type { MessageKey } from "@/i18n/types"
import type { PeopleQuery, PeopleSort, PersonRow, SortOrder } from "@/lib/api"
import { appPathForPerson, isPlainLeftClick, type OpenPerson } from "@/lib/navigation"
import { isAdministrator, lastSignIn, personName } from "@/lib/people"
import { heldPlanChips } from "@/lib/plans"
import { rememberOpenedPerson, takeOpenedPerson, type PeopleCommands } from "@/lib/use-people"
import type { RowSelection } from "@/lib/use-row-selection"

// Fixed widths, so columns stay put whatever a filter shows; once a Plan exists, a box to select
// each row and the Plan column.
const COLUMN_CLASSES = ["col-email", "col-sync", "col-role", "col-state", "col-joined", "col-last", "col-actions"]
const PLAN_COLUMN_CLASSES = [
  "col-select",
  "col-email",
  "col-sync",
  "col-role",
  "col-state",
  "col-plan",
  "col-joined",
  "col-last",
  "col-actions",
]
const ARIA_SORT: Record<SortOrder, "ascending" | "descending"> = { asc: "ascending", desc: "descending" }
const SORT_ICONS = { asc: ArrowUp, desc: ArrowDown }

/**
 * One page of people as a table. Email, Sync, Joined, and Last sign-in sort when their heading is
 * pressed; each email heads its row and opens that person's page. Once a Plan exists, each row has a box that
 * selects it, the header one that selects the page, and each person's Plan has a column: its name
 * with chips. On a narrow screen each row becomes a card that labels its own values, and the
 * sortable headings and the box for the page stay above the cards.
 */
export function PeopleTable({
  people,
  query,
  currentUserId,
  now,
  commands,
  changes,
  selection,
  onSort,
  onOpenPerson,
}: {
  people: PersonRow[]
  query: PeopleQuery
  currentUserId: string
  now: number
  commands: PeopleCommands
  /** Change plan for one person from their row's actions. */
  changes: PlanChanges
  /** Who is selected, once a Plan exists. */
  selection: RowSelection
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
          {planned && <SelectAllHeader people={people} selection={selection} />}
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
            selection={selection}
            columns={columns.length}
            now={now}
            commands={commands}
            changes={changes}
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

/** The header's box, which selects everyone on the page, mixed while only some are. */
function SelectAllHeader({ people, selection }: { people: readonly PersonRow[]; selection: RowSelection }) {
  const { t } = useI18n()
  const chosen = people.filter((person) => selection.ids.has(person.id)).length
  return (
    <th scope="col" role="columnheader" className="person-col-select" data-select-all="true">
      <label className="people-select">
        <Checkbox
          id={SELECT_ALL}
          checked={chosen > 0 && chosen === people.length}
          indeterminate={chosen > 0 && chosen < people.length}
          onCheckedChange={(on) => selection.setAll(people.map((person) => person.id), on)}
        />
        <span className="people-select-label">{t("people.table.selectAll")}</span>
      </label>
    </th>
  )
}

/**
 * A person's Plan: its name, and chips for the default, a limit they are over in Attention Ochre
 * with an icon ("Would be over", neutral, while Plans are off), and an administrator, whom no Plan
 * limits. Which limit they are over follows on a muted line under them.
 */
function PlanCell({ person }: { person: PersonRow }) {
  const i18n = useI18n()
  const plan = person.plan
  return (
    <td role="cell" className="person-col-plan" data-label={i18n.t("people.table.plan")}>
      {plan && (
        <span className="person-plan-cell">
          <span className="person-plan-name" data-none={plan.has ? undefined : true}>
            {plan.has?.name ?? i18n.t("people.table.noPlan")}
          </span>
          <PlanChips chips={heldPlanChips(i18n, plan, isAdministrator(person))} shown />
        </span>
      )}
    </td>
  )
}

function PersonRows({
  person,
  you,
  planned,
  selection,
  columns,
  now,
  commands,
  changes,
  onOpen,
}: {
  person: PersonRow
  you: boolean
  /** A Plan exists, so the row has a box that selects it and a Plan column. */
  planned: boolean
  selection: RowSelection
  /** How many columns the table has, which a row of details spans. */
  columns: number
  now: number
  commands: PeopleCommands
  changes: PlanChanges
  onOpen: OpenPerson
}) {
  const i18n = useI18n()
  const { t } = i18n
  const name = personName(i18n, person)
  const selected = selection.ids.has(person.id)
  useFocusKeptOnLeave()
  return (
    <Fragment>
      <tr role="row" className="person-row" data-selected={planned && selected ? true : undefined}>
        {planned && (
          <td role="cell" className="person-col-select">
            <Checkbox
              aria-label={t("people.table.select", { email: name })}
              checked={selected}
              onCheckedChange={(on) => selection.toggle(person.id, on)}
            />
          </td>
        )}
        <th scope="row" role="rowheader" className="person-col-email">
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
        </th>
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
        <PersonActions person={person} name={name} you={you} commands={commands} changes={changes} />
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

/**
 * A row that leaves the list while it holds focus, as when a change takes its person out of a
 * narrowed list, leaves focus on the list's heading rather than nowhere.
 */
function useFocusKeptOnLeave() {
  useEffect(
    () => () => {
      const active = document.activeElement
      if (active === null || active === document.body) document.getElementById(LIST_TITLE)?.focus({ preventScroll: true })
    },
    [],
  )
}

/**
 * Someone else's actions: the menu, and, once a Plan exists, Change plan in a popover beside it,
 * which gives focus back to the menu as it closes.
 */
function PersonActions({
  person,
  name,
  you,
  commands,
  changes,
}: {
  person: PersonRow
  name: string
  you: boolean
  commands: PeopleCommands
  changes: PlanChanges
}) {
  const cell = useRef<HTMLTableCellElement>(null)
  return (
    <td ref={cell} role="cell" className="person-col-actions">
      {!you && <PersonMenu person={person} name={name} commands={commands} plan={person.plan} />}
      {!you && person.plan && (
        <RowPlanPopover
          person={person}
          commands={commands}
          changes={changes}
          returnFocus={() => cell.current?.querySelector<HTMLElement>("[aria-haspopup='menu']") ?? null}
        />
      )}
    </td>
  )
}
