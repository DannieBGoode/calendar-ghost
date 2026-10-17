import type { I18n } from "@/i18n/translator"
import type {
  OverLimit,
  PeoplePage,
  Person,
  PersonPlanOverview,
  PersonRow,
  PlanAssignments,
  PlanMove,
  PlanSummary,
} from "@/lib/api"
import { personName } from "@/lib/people"
import { planAllowsSentence } from "@/lib/plan-panel"
import { overLimitText } from "@/lib/plans"
import { catalogOrder } from "@/lib/plans-catalog"

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

/** Change plan's choice to follow the Default Plan; no Plan's key is empty. */
export const FOLLOW_DEFAULT = ""

/** Someone whose Plan Change plan changes: who they are, and the Plan they have now. */
export type PlanPerson = Person & { plan: PersonPlanOverview | null }

/** The Plan someone has of their own, by key, or FOLLOW_DEFAULT when they follow the Default Plan. */
function ownChoice(person: PlanPerson): string {
  const has = person.plan?.has
  return has && !has.on_default ? has.key : FOLLOW_DEFAULT
}

/** The choice every one of them has now, which they cannot be given again; null when they differ. */
function sharedChoice(people: readonly PlanPerson[]): string | null {
  const choices = new Set(people.map(ownChoice))
  const [only] = choices
  return choices.size === 1 && only !== undefined ? only : null
}

/** One choice in Change plan: what it is called, what it allows, and, for what they have now, "Current". */
export type ChangeChoice = { value: string; title: string; description: string; unavailable?: string }

/**
 * Change plan's choices for some people: "Follow the default plan" first, saying which Plan that is
 * now, then each Plan, the default first, with what it allows. What every one of them has now is
 * "Current" and cannot be chosen again.
 */
export function changeChoices(i18n: I18n, plans: readonly PlanSummary[], people: readonly PlanPerson[]): ChangeChoice[] {
  const { t } = i18n
  const shared = sharedChoice(people)
  const current = (value: string) => (value === shared ? { unavailable: t("people.plans.change.current") } : {})
  const fallback = plans.find((plan) => plan.is_default)
  return [
    {
      value: FOLLOW_DEFAULT,
      title: t("people.plans.change.follow"),
      description: fallback
        ? t("people.plans.change.followNow", { name: fallback.name })
        : t("people.plans.change.followNone"),
      ...current(FOLLOW_DEFAULT),
    },
    ...catalogOrder(plans).map((plan) => ({
      value: plan.key,
      title: plan.name,
      description: planAllowsSentence(i18n, plan.limits),
      ...current(plan.key),
    })),
  ]
}

/** The Plan a choice in Change plan gives: the one chosen, or for the default, the default now. */
export function chosenPlan(plans: readonly PlanSummary[], choice: string): PlanSummary | undefined {
  return plans.find((plan) => (choice === FOLLOW_DEFAULT ? plan.is_default : plan.key === choice))
}

/** The one person a change is for, when it is for one; their name then says who. */
function onlyOne(i18n: I18n, people: readonly PlanPerson[]): string | null {
  const [first] = people
  return people.length === 1 && first ? personName(i18n, first) : null
}

/** Change plan's title: "Change plan for robin@example.test", or "Change plan for 2 people". */
export function changeTitle(i18n: I18n, people: readonly PlanPerson[]): string {
  const one = onlyOne(i18n, people)
  return one === null
    ? i18n.t("people.plans.change.titleMany", { count: people.length })
    : i18n.t("people.plans.change.title", { person: one })
}

/** Why confirming waits before anything is chosen: "Choose a plan for 2 people." */
export function changeReason(i18n: I18n, people: readonly PlanPerson[]): string {
  const one = onlyOne(i18n, people)
  return one === null
    ? i18n.t("people.plans.change.chooseReasonMany", { count: people.length })
    : i18n.t("people.plans.change.chooseReason", { person: one })
}

/** The name of the Plan someone has now, or "no plan". */
function heldName(i18n: I18n, person: PlanPerson): string {
  return person.plan?.has?.name ?? i18n.t("people.plans.change.noPlan")
}

/** Up to this many people are named in what they have now; more are counted. */
const NAMED = 3

/**
 * Which Plan they have now, before they choose: "robin@example.test and jordan@example.test have
 * Free now.", "All 4 have Free now.", or, when they differ, "They have Free (2) and Pro (1) now."
 */
export function heldNow(i18n: I18n, people: readonly PlanPerson[]): string {
  const { t } = i18n
  const groups = new Map<string, number>()
  for (const person of people) groups.set(heldName(i18n, person), (groups.get(heldName(i18n, person)) ?? 0) + 1)
  const [only] = groups.keys()
  if (groups.size > 1 || only === undefined) {
    const plans = [...groups].map(([name, count]) => t("people.plans.change.heldGroup", { name, count }))
    return t("people.plans.change.heldMixed", { plans: i18n.format.list(plans) })
  }
  const one = onlyOne(i18n, people)
  if (one !== null) return t("people.plans.change.heldOne", { person: one, name: only })
  if (people.length > NAMED) return t("people.plans.change.heldAll", { count: people.length, name: only })
  return t("people.plans.change.heldFew", { people: i18n.format.list(people.map((person) => personName(i18n, person))), name: only })
}

/** Where a choice in Change plan moves people: a Plan of their own, or following the default (`follows`). */
export type ChangeTarget = { plan: PlanSummary | undefined; follows: boolean }

/** What the dry run says a choice would do, and whether anyone would have more than it allows. */
export type ChangeOutcome = { text: string; over: boolean }

/** Where they move, for several people: "They move from Free to Pro.", or to the default plan. */
function moveSentence(i18n: I18n, people: readonly PlanPerson[], { plan, follows }: ChangeTarget): string {
  const { t } = i18n
  const name = plan?.name ?? ""
  const to = follows ? t("people.plans.change.toDefault", { name }) : name
  const from = new Set(people.map((person) => heldName(i18n, person)))
  const [only] = from
  return from.size === 1 && only !== undefined && (follows || only !== name)
    ? t("people.plans.change.moveFrom", { from: only, to })
    : t("people.plans.change.moveTo", { to })
}

/** For several people none of whom would be over: who no longer is, or that they all fit. */
function withinSentence(i18n: I18n, people: readonly PlanPerson[], name: string): string {
  const { t } = i18n
  const relieved = people.filter((person) => person.role !== "installation_administrator" && (person.plan?.over.length ?? 0) > 0)
  const [first] = relieved
  if (relieved.length === 1 && first) return t("people.plans.change.noLongerOverOne", { person: personName(i18n, first) })
  if (relieved.length > 1) return t("people.plans.change.noLongerOver", { count: relieved.length })
  return t("people.plans.change.allWithin", { name })
}

/**
 * What the dry run says a choice in Change plan would do: for one person, what they would have
 * more of than the Plan allows, or that they are within it; for several, where they move, then who
 * would be over, who no longer is, or that they all fit. Nothing until it answers, or when no Plan
 * is the default to follow.
 */
export function changeResult(
  i18n: I18n,
  people: readonly PlanPerson[],
  target: ChangeTarget,
  answer: PlanAssignments | undefined,
): ChangeOutcome {
  const { plan } = target
  if (!plan || !answer) return { text: "", over: false }
  const over = new Set(answer.people.filter((moved) => moved.over.length > 0).map((moved) => moved.user_id))
  const overNames = people.filter((person) => over.has(person.id)).map((person) => personName(i18n, person))
  const verdict = overNote(i18n, overNames, plan.name)
  const one = onlyOne(i18n, people)
  if (one !== null) {
    return { text: verdict ?? i18n.t("people.plans.change.within", { person: one, name: plan.name }), over: verdict !== null }
  }
  return {
    text: i18n.t("people.plans.change.result", {
      move: moveSentence(i18n, people, target),
      over: verdict ?? withinSentence(i18n, people, plan.name),
    }),
    over: verdict !== null,
  }
}

/**
 * What confirms a choice in Change plan: "Give Pro to robin@example.test", "Give Pro to 2 people",
 * "Move robin@example.test to the default plan", or, before a choice, "Change plan".
 */
export function changeConfirm(i18n: I18n, people: readonly PlanPerson[], choice: string | null, plan: PlanSummary | undefined): string {
  const { t } = i18n
  const one = onlyOne(i18n, people)
  if (choice === null) return t("people.plans.change.choose")
  if (choice === FOLLOW_DEFAULT) {
    return one === null
      ? t("people.plans.change.giveDefaultMany", { count: people.length })
      : t("people.plans.change.giveDefault", { person: one })
  }
  const name = plan?.name ?? ""
  return one === null
    ? t("people.plans.assign.give", { name, count: people.length })
    : t("people.plans.change.give", { name, person: one })
}

/** What a change in Change plan did: "robin@example.test now has Pro.", "2 people now follow the default plan." */
export function changedResult(i18n: I18n, people: readonly PlanPerson[], plan: PlanSummary | null | undefined): string {
  const { t } = i18n
  const one = onlyOne(i18n, people)
  if (plan === null) {
    return one === null
      ? t("people.plans.change.followedMany", { count: people.length })
      : t("people.plans.change.followed", { person: one })
  }
  const name = plan?.name ?? ""
  return one === null
    ? t("people.plans.assign.given", { count: people.length, name })
    : t("people.plans.assign.givenOne", { person: one, name })
}
