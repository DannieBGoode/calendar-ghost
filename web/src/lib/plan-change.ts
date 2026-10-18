import type { I18n } from "@/i18n/translator"
import type { Person, PersonPlanOverview, PlanAssignments, PlanSummary } from "@/lib/api"
import { personName } from "@/lib/people"
import { wouldBeOver } from "@/lib/plan-assignment"
import { planLimitsSummary } from "@/lib/plan-panel"
import { overLimitText } from "@/lib/plans"
import { catalogOrder } from "@/lib/plans-catalog"

/**
 * The words and choices of Change plan: one option per Plan, the default first, where choosing the
 * default means following it; what each person has now; what a dry run says a choice would do; and
 * what the change did. Counts come from the Operator Overview's dry run; nothing here counts on its
 * own.
 */

/** Someone whose Plan Change plan changes: who they are, and the Plan they have now. */
export type PlanPerson = Person & { plan: PersonPlanOverview | null }

/** Change plan's choice that leaves someone with no Plan, offered only while no Plan is the default. No Plan's key is empty. */
export const NO_PLAN = ""

/** A badge after an option's name: the default Plan's, or who has the option now. */
type OptionBadge = { text: string; kind: "default" | "current" }

/** One option in Change plan: a Plan by its key, or NO_PLAN, its name, its limits in short, and its badges. */
export type ChangeOption = { value: string; title: string; summary: string; badges: OptionBadge[] }

/**
 * What someone has now, as Change plan offers it: the default Plan, whether they follow it or were
 * given it as their own, another Plan of their own, or NO_PLAN.
 */
function currentChoice(person: PlanPerson): string {
  return person.plan?.has?.key ?? NO_PLAN
}

/**
 * What every one of them has now, which Change plan starts from, and which Save leaves as it is;
 * null when they differ.
 */
export function sharedChoice(plans: readonly PlanSummary[], people: readonly PlanPerson[]): string | null {
  const choices = new Set(people.map(currentChoice))
  const [only] = choices
  if (choices.size !== 1 || only === undefined) return null
  return offered(plans, only) ? only : null
}

/** Whether Change plan offers a choice: a Plan that exists, or No plan while no Plan is the default. */
export function offered(plans: readonly PlanSummary[], choice: string): boolean {
  return choice === NO_PLAN ? !plans.some((plan) => plan.is_default) : plans.some((plan) => plan.key === choice)
}

/** How many of them have each choice now. */
function holding(people: readonly PlanPerson[]): Map<string, number> {
  const counts = new Map<string, number>()
  for (const person of people) counts.set(currentChoice(person), (counts.get(currentChoice(person)) ?? 0) + 1)
  return counts
}

/** Who has an option now: "Current" when every one of them does, otherwise how many ("2 have it"). */
function holdingBadge({ t }: I18n, held: number, all: number): OptionBadge[] {
  if (held === 0) return []
  return [{ text: held === all ? t("people.plans.change.current") : t("people.plans.change.holding", { count: held }), kind: "current" }]
}

/**
 * Change plan's options for some people: each Plan once, the default first with its badge, each
 * with its limits in short, and, only while no Plan is the default, No plan last. What they have now
 * is marked "Current", or, when they differ, how many have each.
 */
export function changeOptions(i18n: I18n, plans: readonly PlanSummary[], people: readonly PlanPerson[]): ChangeOption[] {
  const { t } = i18n
  const counts = holding(people)
  const badges = (value: string) => holdingBadge(i18n, counts.get(value) ?? 0, people.length)
  const options = catalogOrder(plans).map((plan) => ({
    value: plan.key,
    title: plan.name,
    summary: planLimitsSummary(i18n, plan.limits),
    badges: [...(plan.is_default ? [{ text: t("people.plans.isDefault"), kind: "default" as const }] : []), ...badges(plan.key)],
  }))
  if (plans.some((plan) => plan.is_default)) return options
  return [
    ...options,
    { value: NO_PLAN, title: t("people.plans.change.noPlan"), summary: t("people.plans.change.noPlanSummary"), badges: badges(NO_PLAN) },
  ]
}

/** The Plan a choice gives: the one chosen, or null for no Plan. */
export function chosenPlan(plans: readonly PlanSummary[], choice: string): PlanSummary | null {
  return plans.find((plan) => plan.key === choice) ?? null
}

/** What a choice sends: a Plan's key, or null for the default, which they then follow, or for no Plan. */
export function changeMove(plans: readonly PlanSummary[], choice: string): string | null {
  const plan = chosenPlan(plans, choice)
  return plan === null || plan.is_default ? null : plan.key
}

/** The one person a change is for, when it is for one; their name then says who. */
function onlyOne(i18n: I18n, people: readonly PlanPerson[]): string | null {
  const [first] = people
  return people.length === 1 && first ? personName(i18n, first) : null
}

/** What the dry run says a choice would do, under it, and whether anyone would be over a limit. */
export type ChoiceVerdict = { text: string; over: boolean }

/**
 * What the dry run says a choice would do: for one person, each limit they would be over, or that
 * they are within every limit; for several, who would be over and their limits when it is one, how
 * many when more, or that nobody would. Nothing until it answers.
 */
export function choiceVerdict(i18n: I18n, people: readonly PlanPerson[], answer: PlanAssignments | undefined): ChoiceVerdict | null {
  if (!answer) return null
  const { t } = i18n
  const over = answer.people.filter((moved) => moved.over.length > 0)
  const [first] = over
  if (onlyOne(i18n, people) !== null) {
    const limits = first ? wouldBeOver(i18n, first.over) : null
    return limits === null ? { text: t("people.plans.change.within"), over: false } : { text: limits, over: true }
  }
  if (!first) return { text: t("people.plans.change.nobodyOver"), over: false }
  if (over.length > 1) return { text: t("people.plans.change.overMany", { count: over.length }), over: true }
  const who = people.find((person) => person.id === first.user_id)
  const limits = i18n.format.list(first.over.map((limit) => overLimitText(i18n, limit)))
  return { text: t("people.plans.change.overOne", { person: who ? personName(i18n, who) : t("people.noEmail"), limits }), over: true }
}

/** Change plan's title where the people are not otherwise named: "Change plan for robin@example.test", "Change plan for 2 people". */
export function changeTitle(i18n: I18n, people: readonly PlanPerson[]): string {
  const one = onlyOne(i18n, people)
  return one === null
    ? i18n.t("people.plans.change.titleMany", { count: people.length })
    : i18n.t("people.plans.change.title", { person: one })
}

/** What a change did: "robin@example.test now has Pro.", "2 people now have Pro.", or that they have no Plan now. */
export function changedResult(i18n: I18n, people: readonly PlanPerson[], plan: PlanSummary | null): string {
  const { t } = i18n
  const one = onlyOne(i18n, people)
  if (plan === null) {
    return one === null
      ? t("people.plans.change.noPlanResultMany", { count: people.length })
      : t("people.plans.change.noPlanResult", { person: one })
  }
  return one === null
    ? t("people.plans.assign.given", { count: people.length, name: plan.name })
    : t("people.plans.assign.givenOne", { person: one, name: plan.name })
}
