import { Info, RefreshCw, TriangleAlert } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import { SearchField } from "@/components/search-field"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Skeleton } from "@/components/ui/skeleton"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import type { OverLimit, PersonRow, PlanAssignments, PlanSummary } from "@/lib/api"
import { personName } from "@/lib/people"
import { heldPlanLine, overNote, wouldBeOver, type AssignCandidates } from "@/lib/plan-assignment"
import { usePlanCandidates, usePlanDryRun } from "@/lib/use-plan-assignment"
import type { PlanCommands } from "@/lib/use-plans"

/** Whom Assign people has chosen, by id. */
type Chosen = ReadonlySet<string>

/**
 * Assign people, from a Plan: a search by email, then a checklist of everyone found who does not
 * have the Plan yet, each with the Plan they have and, from a dry run that gives nothing, what they
 * would be over. Administrators come last, never limited. Whom it chose stays chosen while the
 * search changes. Giving the Plan is one command, all or none; while it is on its way every
 * control keeps focus and waits, and a refusal shows under the footer.
 */
export function PlanAssign({
  plan,
  enabled,
  currentUserId,
  assign,
  onGiven,
  onCancel,
}: {
  plan: PlanSummary
  /** Plans limit people now, so who would be over takes the attention tone. */
  enabled: boolean
  currentUserId: string
  assign: PlanCommands["assign"]
  onGiven: (answer: PlanAssignments) => void
  onCancel: () => void
}) {
  const i18n = useI18n()
  const { t } = i18n
  const base = `plan-assign-${plan.key}`
  const [search, setSearch] = useState("")
  const [chosen, setChosen] = useState<Chosen>(new Set())
  const pending = assign.isPending
  const candidates = usePlanCandidates(plan.key, search, pending)
  const found = candidates.data
  const dryRun = usePlanDryRun(plan.key, found?.members.map((person) => person.id) ?? [], pending)
  const overOf = new Map(dryRun.data?.people.map((person) => [person.user_id, person.over]))
  const heading = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    heading.current?.focus()
  }, [])

  function toggle(person: PersonRow, checked: boolean) {
    setChosen((current) => {
      const next = new Set(current)
      if (checked) next.add(person.id)
      else next.delete(person.id)
      return next
    })
  }

  function give() {
    if (chosen.size === 0 || pending) return
    assign.mutate(
      { from: plan.key, moves: [{ plan: plan.key, userIds: [...chosen] }] },
      { onSuccess: ([answer]) => answer && onGiven(answer) },
    )
  }

  const overChosen = (found?.members ?? []).filter((person) => chosen.has(person.id) && (overOf.get(person.id)?.length ?? 0) > 0)
  const note = overNote(i18n, overChosen.map((person) => personName(i18n, person)), plan.name)
  return (
    <section id={base} className="plan-assign" aria-labelledby={`${base}-title`}>
      <div className="plan-assign-head">
        <h3 id={`${base}-title`} ref={heading} tabIndex={-1}>
          {t("people.plans.assign.title")}
        </h3>
        <p className="plan-assign-intro">{t("people.plans.assign.intro", { name: plan.name })}</p>
      </div>
      <SearchField
        id={`${base}-search`}
        label={t("people.filters.search")}
        placeholder={t("people.filters.searchPlaceholder")}
        clearLabel={t("people.filters.clearSearch")}
        query={search}
        onSearch={setSearch}
      />
      <Candidates
        base={base}
        query={candidates}
        overOf={overOf}
        enabled={enabled}
        currentUserId={currentUserId}
        chosen={chosen}
        pending={pending}
        onToggle={toggle}
      />
      {note && (
        <p className="plan-assign-note" data-tone={enabled ? "attention" : undefined}>
          {enabled ? <TriangleAlert aria-hidden="true" /> : <Info aria-hidden="true" />}
          <span>{note}</span>
        </p>
      )}
      <AssignFooter base={base} plan={plan} count={chosen.size} pending={pending} onGive={give} onCancel={onCancel} />
      {assign.error && (
        <p className="field-error" role="alert">
          {apiErrorMessage(i18n, assign.error)}
        </p>
      )}
    </section>
  )
}

type CandidatesQuery = ReturnType<typeof usePlanCandidates>

/**
 * The people found: while the first search is on its way, skeletons in their shape; when they
 * cannot be read, why, with Try again; otherwise how many were found, then the checklist.
 */
function Candidates({
  base,
  query,
  ...list
}: {
  base: string
  query: CandidatesQuery
  overOf: ReadonlyMap<string, OverLimit[]>
  enabled: boolean
  currentUserId: string
  chosen: Chosen
  pending: boolean
  onToggle: (person: PersonRow, checked: boolean) => void
}) {
  const { t } = useI18n()
  if (query.isPending) {
    return (
      <div className="plan-assign-loading" role="status" aria-busy="true" aria-label={t("people.plans.assign.loading")}>
        <Skeleton className="h-11 w-full" />
        <Skeleton className="h-11 w-full" />
      </div>
    )
  }
  if (!query.data) {
    return (
      <div className="plan-assign-error" role="alert">
        <span>{t("people.plans.assign.loadError")}</span>
        <Button type="button" variant="outline" size="sm" onClick={() => void query.refetch()}>
          <RefreshCw aria-hidden="true" />
          {t("people.plans.tryAgain")}
        </Button>
      </div>
    )
  }
  return <Checklist base={base} found={query.data} {...list} />
}

/** How many were found, then each person found who is a member, and under them the administrators. */
function Checklist({
  base,
  found,
  ...row
}: {
  base: string
  found: AssignCandidates
  overOf: ReadonlyMap<string, OverLimit[]>
  enabled: boolean
  currentUserId: string
  chosen: Chosen
  pending: boolean
  onToggle: (person: PersonRow, checked: boolean) => void
}) {
  const { t } = useI18n()
  const { members, administrators, more } = found
  const count = members.length + administrators.length
  const foundText =
    count === 0
      ? t("people.plans.assign.nobody")
      : t(more ? "people.plans.assign.foundMore" : "people.plans.assign.found", { count })
  return (
    <div className="plan-assign-list">
      <p className="plan-assign-found" role="status">
        {foundText}
      </p>
      {count > 0 && (
        <div className="plan-assign-box">
          {members.length > 0 && (
            <ul className="plan-assign-people" aria-label={t("people.plans.assign.title")}>
              {members.map((person) => (
                <CandidateRow key={person.id} base={base} person={person} administrator={false} {...row} />
              ))}
            </ul>
          )}
          {administrators.length > 0 && (
            <>
              <p id={`${base}-administrators`} className="plan-assign-group">
                {t("people.plans.assign.administrators")}
              </p>
              <ul className="plan-assign-people" aria-labelledby={`${base}-administrators`}>
                {administrators.map((person) => (
                  <CandidateRow key={person.id} base={base} person={person} administrator {...row} />
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </div>
  )
}

/**
 * One person to choose: their email, "You" for the reader, the Plan they have or, for an
 * administrator, that no Plan limits them, and what they would be over, which their box names.
 */
function CandidateRow({
  base,
  person,
  administrator,
  overOf,
  enabled,
  currentUserId,
  chosen,
  pending,
  onToggle,
}: {
  base: string
  person: PersonRow
  administrator: boolean
  overOf: ReadonlyMap<string, OverLimit[]>
  enabled: boolean
  currentUserId: string
  chosen: Chosen
  pending: boolean
  onToggle: (person: PersonRow, checked: boolean) => void
}) {
  const i18n = useI18n()
  const { t } = i18n
  const id = `${base}-${person.id}`
  const over = administrator ? null : wouldBeOver(i18n, overOf.get(person.id) ?? [])
  return (
    <li className="plan-assign-person" data-checked={chosen.has(person.id) || undefined}>
      <Checkbox
        id={id}
        checked={chosen.has(person.id)}
        pending={pending}
        aria-describedby={over ? `${id}-held ${id}-over` : `${id}-held`}
        onCheckedChange={(checked) => onToggle(person, checked)}
      />
      <div className="plan-assign-who">
        <label htmlFor={id}>
          <span>{personName(i18n, person)}</span>
          {person.id === currentUserId && <Badge variant="outline">{t("people.you")}</Badge>}
        </label>
        <span id={`${id}-held`} className="plan-assign-held">
          {administrator ? t("people.plans.assign.neverLimited") : heldPlanLine(i18n, person)}
        </span>
        {over && (
          <span id={`${id}-over`} className="plan-assign-over" data-tone={enabled ? "attention" : undefined}>
            {enabled && <TriangleAlert aria-hidden="true" />}
            {over}
          </span>
        )}
      </div>
    </li>
  )
}

/**
 * Give the Plan to whoever was chosen, the one primary action; it waits, with why, until someone is
 * chosen. Then Cancel, and how many are chosen.
 */
function AssignFooter({
  base,
  plan,
  count,
  pending,
  onGive,
  onCancel,
}: {
  base: string
  plan: PlanSummary
  count: number
  pending: boolean
  onGive: () => void
  onCancel: () => void
}) {
  const { t } = useI18n()
  const reasonId = `${base}-give-reason`
  const none = count === 0
  return (
    <>
      <div className="plan-assign-foot">
        <Button
          type="button"
          aria-disabled={none || pending || undefined}
          aria-busy={pending || undefined}
          aria-describedby={none ? reasonId : undefined}
          onClick={onGive}
        >
          {none ? t("people.plans.assign.giveNone", { name: plan.name }) : t("people.plans.assign.give", { count, name: plan.name })}
        </Button>
        <Button type="button" variant="ghost" aria-disabled={pending || undefined} onClick={() => !pending && onCancel()}>
          {t("people.plans.assign.cancel")}
        </Button>
        <span className="plan-assign-selected">{t("people.plans.assign.selected", { count })}</span>
      </div>
      {none && (
        <p id={reasonId} className="field-hint">
          {t("people.plans.assign.giveReason", { name: plan.name })}
        </p>
      )}
    </>
  )
}
