import { Info, RefreshCw, TriangleAlert } from "lucide-react"
import { useState, type ReactNode } from "react"

import { SearchField } from "@/components/search-field"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Skeleton } from "@/components/ui/skeleton"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import type { OverLimit, PersonRow, PlanAssignments, PlanSummary } from "@/lib/api"
import { isAdministrator, personName } from "@/lib/people"
import { giveWait, heldPlanLine, overNote, PEOPLE_PER_ASSIGNMENT, wouldBeOver, type AssignCandidates } from "@/lib/plan-assignment"
import { usePlanCandidates, usePlanDryRun } from "@/lib/use-plan-assignment"
import type { PlanCommands } from "@/lib/use-plans"

/** Whom Assign people has chosen, by id, kept whole while a search hides them. */
type Chosen = ReadonlyMap<string, PersonRow>

/**
 * Whom the dry run asks about: everyone found whom a Plan could limit, then anyone chosen whom the
 * search hides now, so what they would be over is still said. At most PEOPLE_PER_ASSIGNMENT, as
 * the server answers, so the last found whom nobody chose make room for the chosen.
 */
function dryRunIds(found: readonly PersonRow[], chosen: Chosen): string[] {
  const shown = new Set(found.map((person) => person.id))
  const limited = [...chosen.values()].filter((person) => !isAdministrator(person))
  const room = Math.max(0, PEOPLE_PER_ASSIGNMENT - limited.length)
  const others = new Set(found.filter((person) => !chosen.has(person.id)).slice(0, room))
  const asked = found.filter((person) => chosen.has(person.id) || others.has(person))
  const hidden = limited.filter((person) => !shown.has(person.id))
  return [...asked, ...hidden].slice(0, PEOPLE_PER_ASSIGNMENT).map((person) => person.id)
}

/**
 * The People tab of a Plan's panel. Assign people first: a search by email, then a checklist of
 * everyone found who does not have the Plan yet, each with the Plan they have and, from a dry run
 * that gives nothing, what they would be over. Administrators come last, never limited. Whom it
 * chose stays chosen while the search changes. Then `children`, who has the Plan now. Giving the
 * Plan is one command, all or none, from the panel's footer; while it is on its way every control
 * keeps focus and waits, and a refusal of it, not of its Undo, shows under the footer. Once given,
 * nobody is chosen, ready for more. Giving the Default Plan means following it, so it leaves them
 * with no Plan of their own, as Change plan does, and they move with it when the default changes.
 */
export function PlanAssign({
  plan,
  enabled,
  currentUserId,
  assign,
  onGiven,
  onCancel,
  children,
}: {
  plan: PlanSummary
  /** Plans limit people now, so who would be over takes the attention tone. */
  enabled: boolean
  currentUserId: string
  assign: PlanCommands["assign"]
  onGiven: (answer: PlanAssignments) => void
  onCancel: () => void
  children?: ReactNode
}) {
  const i18n = useI18n()
  const { t } = i18n
  const base = `plan-assign-${plan.key}`
  const [search, setSearch] = useState("")
  const [chosen, setChosen] = useState<Chosen>(new Map())
  const pending = assign.isPending
  // The Default Plan is given as following it: no Plan of their own.
  const given = plan.is_default ? null : plan.key
  const candidates = usePlanCandidates(plan.key, search, pending)
  const found = candidates.data
  const dryRun = usePlanDryRun(given, dryRunIds(found?.members ?? [], chosen), pending)
  const overOf = new Map(dryRun.data?.people.map((person) => [person.user_id, person.over]))
  const refused = giveRefusal(assign, plan.key)

  function toggle(person: PersonRow, checked: boolean) {
    setChosen((current) => {
      const next = new Map(current)
      if (checked) next.set(person.id, person)
      else next.delete(person.id)
      return next
    })
  }

  function give() {
    if (chosen.size === 0 || chosen.size > PEOPLE_PER_ASSIGNMENT || pending) return
    assign.mutate(
      { from: plan.key, via: "give", moves: [{ plan: given, userIds: [...chosen.keys()] }] },
      {
        onSuccess: ([answer]) => {
          setChosen(new Map())
          if (answer) onGiven(answer)
        },
      },
    )
  }

  return (
    <>
      <div className="plan-panel-body">
        <section id={base} className="plan-assign" aria-labelledby={`${base}-title`}>
          <div className="plan-assign-head">
            <h4 id={`${base}-title`}>{t("people.plans.assign.title")}</h4>
            <p className="plan-assign-intro">
              {t(plan.is_default ? "people.plans.assign.introDefault" : "people.plans.assign.intro", { name: plan.name })}
            </p>
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
          <OverNote plan={plan} chosen={chosen} overOf={overOf} enabled={enabled} />
        </section>
        {children}
      </div>
      <AssignFooter
        base={base}
        plan={plan}
        count={chosen.size}
        pending={pending}
        refusal={refused && apiErrorMessage(i18n, refused)}
        onGive={give}
        onCancel={onCancel}
      />
    </>
  )
}

/** Why giving the Plan was refused, to show under the footer; Change plan's shows under it, and Undo's in a toast. */
function giveRefusal(assign: PlanCommands["assign"], key: string): Error | null {
  return assign.error && assign.variables.from === key && assign.variables.via === "give" ? assign.error : null
}

/**
 * What it means for the people chosen who would be over, whether or not the search shows them now:
 * they keep everything, but add nothing more. In Attention Ochre with its icon while Plans are on,
 * neutral while off.
 */
function OverNote({
  plan,
  chosen,
  overOf,
  enabled,
}: {
  plan: PlanSummary
  chosen: Chosen
  overOf: ReadonlyMap<string, OverLimit[]>
  enabled: boolean
}) {
  const i18n = useI18n()
  const over = [...chosen.values()].filter((person) => (overOf.get(person.id)?.length ?? 0) > 0)
  const note = overNote(i18n, over.map((person) => personName(i18n, person)), plan.name)
  if (!note) return null
  return (
    <p className="plan-assign-note" data-tone={enabled ? "attention" : undefined}>
      {enabled ? <TriangleAlert aria-hidden="true" /> : <Info aria-hidden="true" />}
      <span>{note}</span>
    </p>
  )
}

type CandidatesQuery = ReturnType<typeof usePlanCandidates>

/** What each person found needs from Assign people beside the person. */
type RowProps = {
  overOf: ReadonlyMap<string, OverLimit[]>
  enabled: boolean
  currentUserId: string
  chosen: Chosen
  pending: boolean
  onToggle: (person: PersonRow, checked: boolean) => void
}

/**
 * The people found: while the first search is on its way, skeletons in their shape; when they
 * cannot be read, why, with Try again; otherwise how many were found, then the checklist.
 */
function Candidates({ base, query, ...list }: { base: string; query: CandidatesQuery } & RowProps) {
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
function Checklist({ base, found, ...row }: { base: string; found: AssignCandidates } & RowProps) {
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
}: { base: string; person: PersonRow; administrator: boolean } & RowProps) {
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
 * The panel's footer: give the Plan to whoever was chosen, the one primary action, which waits,
 * with why, until someone is chosen and while too many are. Then Cancel, which closes the panel,
 * how many are chosen, and why the last give was refused.
 */
function AssignFooter({
  base,
  plan,
  count,
  pending,
  refusal,
  onGive,
  onCancel,
}: {
  base: string
  plan: PlanSummary
  count: number
  pending: boolean
  refusal: string | null
  onGive: () => void
  onCancel: () => void
}) {
  const i18n = useI18n()
  const { t } = i18n
  const reasonId = `${base}-give-reason`
  const none = count === 0
  const reason = giveWait(i18n, plan.name, count)
  return (
    <div className="plan-panel-foot">
      <div className="plan-panel-actions">
        <Button
          type="button"
          aria-disabled={reason !== null || pending || undefined}
          aria-busy={pending || undefined}
          aria-describedby={reason === null ? undefined : reasonId}
          onClick={onGive}
        >
          {none ? t("people.plans.assign.giveNone", { name: plan.name }) : t("people.plans.assign.give", { count, name: plan.name })}
        </Button>
        <Button type="button" variant="ghost" aria-disabled={pending || undefined} onClick={() => !pending && onCancel()}>
          {t("people.plans.assign.cancel")}
        </Button>
        <span className="plan-panel-status plan-assign-selected">{t("people.plans.assign.selected", { count })}</span>
      </div>
      {reason !== null && (
        <p id={reasonId} className="field-hint">
          {reason}
        </p>
      )}
      {refusal && (
        <p className="field-error" role="alert">
          {refusal}
        </p>
      )}
    </div>
  )
}
