import type { I18n } from "@/i18n/translator"
import type { OverLimit, PeoplePage, PersonRow, PlanAssignments, PlanMove } from "@/lib/api"
import { overLimitText } from "@/lib/plans"

/**
 * The words and choices of Assign people: who may get a Plan, what each has now and would be
 * over, and what giving it did. Counts come from the Operator Overview's dry run; nothing here
 * counts on its own.
 */

/** Who Assign people lists: everyone found who does not have the Plan yet, administrators apart. */
export type AssignCandidates = {
  members: PersonRow[]
  /** Listed last: no Plan limits them, whatever Plan they have. */
  administrators: PersonRow[]
  /** More people match than one page lists, so a search finds the others. */
  more: boolean
}

export function assignCandidates(page: PeoplePage, plan: string): AssignCandidates {
  const others = page.users.filter((person) => person.plan?.has?.key !== plan)
  return {
    members: others.filter((person) => person.role !== "installation_administrator"),
    administrators: others.filter((person) => person.role === "installation_administrator"),
    more: page.total > page.users.length,
  }
}

/** The Plan someone has now, as Assign people says it: "Has Free, the default", "Has Pro", or none. */
export function heldPlanLine({ t }: I18n, person: PersonRow): string {
  const has = person.plan?.has
  if (!has) return t("people.plans.assign.hasNone")
  return has.on_default ? t("people.plans.assign.hasDefault", { name: has.name }) : t("people.plans.assign.has", { name: has.name })
}

/** Each limit someone would have more of under the Plan, from a dry run: "Would be over: 3 rules, 1 allowed". */
export function wouldBeOver(i18n: I18n, over: readonly OverLimit[]): string | null {
  if (over.length === 0) return null
  return i18n.t("people.plans.assign.wouldBeOver", { limits: i18n.format.list(over.map((limit) => overLimitText(i18n, limit))) })
}

/** What it means for the people chosen who would be over: they keep everything, but add nothing more. */
export function overNote({ t }: I18n, over: readonly string[], plan: string): string | null {
  const [first] = over
  if (first === undefined) return null
  return over.length === 1
    ? t("people.plans.assign.overNoteOne", { person: first, name: plan })
    : t("people.plans.assign.overNote", { count: over.length, name: plan })
}

/** Someone given a Plan, by email, as People names them; the upgraded first User may have none. */
function movedName({ t }: I18n, person: PlanMove): string {
  return person.email ?? t("people.noEmail")
}

/** What giving the Plan did: "alex@example.test now has Free." or "2 people now have Free." */
export function assignedResult(i18n: I18n, answer: PlanAssignments, plan: string): string {
  const [only] = answer.people
  if (answer.people.length === 1 && only) {
    return i18n.t("people.plans.assign.givenOne", { person: movedName(i18n, only), name: plan })
  }
  return i18n.t("people.plans.assign.given", { count: answer.people.length, name: plan })
}

/** One call that gives one Plan, or the Default Plan with null, to some people. */
export type AssignMove = { plan: string | null; userIds: string[] }

/**
 * What Undo sends: each person back to the Plan they had, their own by its key, or the Default Plan
 * by having none of their own, in the order first named.
 */
export function undoMoves(answer: PlanAssignments): AssignMove[] {
  const moves = new Map<string | null, string[]>()
  for (const person of answer.people) {
    const plan = person.had && !person.had.on_default ? person.had.key : null
    moves.set(plan, [...(moves.get(plan) ?? []), person.user_id])
  }
  return [...moves].map(([plan, userIds]) => ({ plan, userIds }))
}

/** What Undo did: "alex@example.test has their plan back." or "2 people have their plans back." */
export function restoredResult(i18n: I18n, answer: PlanAssignments): string {
  const [only] = answer.people
  if (answer.people.length === 1 && only) {
    return i18n.t("people.plans.assign.restoredOne", { person: movedName(i18n, only) })
  }
  return i18n.t("people.plans.assign.restored", { count: answer.people.length })
}
