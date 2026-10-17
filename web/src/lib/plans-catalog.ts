import type { I18n } from "@/i18n/translator"
import type { PeoplePage, PlanSummary, PlansOverview, SyncInterval } from "@/lib/api"
import { personName } from "@/lib/people"
import { limitedPeople } from "@/lib/plans"
import type { SettingChange } from "@/lib/use-plans"

/**
 * The Plans tab's words for the catalog of Plans: the status card's sentence and facts, each
 * Plan's cells and row menu, and what a change of the Plans setting did. Cells and facts hold nouns
 * and numbers; sentences belong to the card, the menu's descriptions, and results.
 */

/** The Plans as the catalog lists them: the default first, then the others as the server orders them, by name. */
export function catalogOrder(plans: readonly PlanSummary[]): PlanSummary[] {
  return [...plans.filter((plan) => plan.is_default), ...plans.filter((plan) => !plan.is_default)]
}

/** How many of the people the Plans limit have more than their Plan allows, whether or not Plans are on. */
export function overPeople(plans: readonly PlanSummary[]): number {
  return plans.reduce((total, plan) => total + plan.over_people, 0)
}

/** One count in a Plan's column: its number, or, muted, "Unlimited" or "None" for a Plan that includes none. */
export type CountCell = { text: string; muted: boolean }

export function countCell({ t, format }: I18n, value: number | null): CountCell {
  if (value === null) return { text: t("people.plans.catalog.unlimited"), muted: true }
  if (value === 0) return { text: t("people.plans.catalog.none"), muted: true }
  return { text: format.number(value), muted: false }
}

/** How soon a Plan's rules sync, in a table cell's words: "Instant", "Every 5 min". */
export function speedLabel({ t }: I18n, interval: SyncInterval): string {
  return t(`people.plans.speed.${interval}`)
}

function defaultName({ plans, default_plan }: PlansOverview): string | null {
  return plans.find((plan) => plan.key === default_plan)?.name ?? null
}

/** What turning Plans on would do: whom it limits, and how many of them have more than their Plan allows. */
function wouldLimit({ t }: I18n, limited: number, over: number): string {
  if (limited === 0) return t("people.plans.status.wouldLimitNobody")
  if (over === 0) return t("people.plans.status.wouldLimit", { count: limited })
  return t("people.plans.status.wouldLimitOver", { count: over, people: t("people.plans.status.people", { count: limited }) })
}

/**
 * The status card's one sentence, with `<strong>` around the counts and the Plan it names: what
 * Plans do now while on, and while off what turning them on would do, keeping every Plan, and
 * adding No limits as the default when there is none.
 */
export function statusSentence(i18n: I18n, overview: PlansOverview): string {
  const { t } = i18n
  const limited = limitedPeople(overview.plans)
  const name = defaultName(overview)
  if (overview.enabled) {
    return limited > 0
      ? t("people.plans.status.onLimits", { count: limited, name: name ?? "" })
      : t("people.plans.status.onNobody", { name: name ?? "" })
  }
  if (overview.plans.length === 0) return t("people.plans.status.offNoPlans")
  const parts = {
    kept: t("people.plans.status.kept", { count: overview.plans.length }),
    impact: wouldLimit(i18n, limited, overPeople(overview.plans)),
  }
  return name === null ? t("people.plans.status.offSentenceNoDefault", parts) : t("people.plans.status.offSentence", parts)
}

/**
 * The status card's sentence while a Plan's panel is open beside it, shorter, as the card then
 * keeps only its title, this, and the switch: "They limit 2 people. People without a plan get No
 * limits.", and while off what turning Plans on would do.
 */
export function compactStatusSentence(i18n: I18n, overview: PlansOverview): string {
  const { t } = i18n
  const limited = limitedPeople(overview.plans)
  if (overview.enabled) {
    const name = defaultName(overview) ?? ""
    return limited > 0
      ? t("people.plans.status.compactOn", { count: limited, name })
      : t("people.plans.status.compactOnNobody", { name })
  }
  if (overview.plans.length === 0) return t("people.plans.status.compactOffNoPlans")
  return t("people.plans.status.compactOff", { impact: wouldLimit(i18n, limited, overPeople(overview.plans)) })
}

/** One of the status card's facts; `over` counts who is over a limit, for the fact that shows them. */
export type PlansFact = {
  id: "limited" | "over" | "default" | "administrators"
  label: string
  value: string
  /** In Attention Ochre with an icon: people are over a limit Plans enforce now. */
  attention: boolean
  over: number
}

function peopleCount({ t }: I18n, count: number): string {
  return count === 0 ? t("people.plans.status.nobody") : t("people.plans.status.people", { count })
}

/**
 * The status card's facts: whom Plans limit, who is over a limit, the Default Plan, and who is
 * never limited. While Plans are off they say what turning them on would do, and nothing takes the
 * attention tone, since nothing is enforced. None before any Plan exists. Who is never limited is
 * left out when the answer has no count of them, as a server older than the page sends, rather
 * than shown without its number.
 */
export function statusFacts(i18n: I18n, overview: PlansOverview): PlansFact[] {
  const { t } = i18n
  if (overview.plans.length === 0) return []
  const { enabled, administrators } = overview
  const over = overPeople(overview.plans)
  const fact = (id: PlansFact["id"], label: string, value: string, count = 0): PlansFact => ({
    id,
    label,
    value,
    attention: enabled && count > 0,
    over: count,
  })
  const facts = [
    fact(
      "limited",
      t(enabled ? "people.plans.status.limited" : "people.plans.status.wouldLimitFact"),
      peopleCount(i18n, limitedPeople(overview.plans)),
    ),
    fact("over", t(enabled ? "people.plans.status.over" : "people.plans.status.wouldBeOver"), peopleCount(i18n, over), over),
    fact("default", t("people.plans.status.default"), defaultName(overview) ?? t("people.plans.status.noDefault")),
  ]
  if (!Number.isFinite(administrators)) return facts
  const never = t("people.plans.status.administrators", { count: administrators })
  return [...facts, fact("administrators", t("people.plans.status.neverLimited"), never)]
}

/**
 * What Make default says it does: whom it moves, everyone without a Plan of their own, and how many
 * they are now. Without a count, as a server older than the page sends, it names whom it moves and
 * never says that nobody moves.
 */
export function makeDefaultHint({ t }: I18n, { name }: Pick<PlanSummary, "name">, followers: number): string {
  if (!Number.isFinite(followers)) return t("people.plans.menu.makeDefaultMovesUncounted", { name })
  return followers > 0
    ? t("people.plans.menu.makeDefaultMoves", { count: followers, name })
    : t("people.plans.menu.makeDefaultNobody", { name })
}

/**
 * Why Remove cannot remove a Plan, as its menu item says, or null when it can. The default waits
 * for another default; a Plan people have names the first of them by email from `holders`, the
 * first page of who has it, and counts them until they are known or when they cannot be read.
 */
export function removeRefusal(i18n: I18n, plan: PlanSummary, holders: PeoplePage | undefined): string | null {
  const { t } = i18n
  if (plan.is_default) return t("people.plans.menu.removeDefault")
  if (plan.people === 0) return null
  if (!holders || holders.users.length === 0) {
    return t("people.plans.menu.removeInUse", { count: plan.people, name: plan.name })
  }
  const names = holders.users.map((person) => personName(i18n, person))
  const more = holders.total - names.length
  const people = i18n.format.list(more > 0 ? [...names, t("people.plans.menu.more", { count: more })] : names)
  return t("people.plans.menu.removeInUseNamed", { count: holders.total, people, name: plan.name })
}

/**
 * What a change of the Plans setting did, as its toast says it: whom Plans limit once on, naming
 * the No limits Plan the server made the default when there was none; that nobody is limited once
 * off; or the new Default Plan.
 */
export function settingResult(i18n: I18n, before: PlansOverview, after: PlansOverview): string {
  const { t } = i18n
  if (before.enabled !== after.enabled) {
    if (!after.enabled) return t("people.plans.results.off")
    const made = after.plans.find(
      (plan) => plan.key === after.default_plan && !before.plans.some((known) => known.key === plan.key),
    )
    if (made) return t("people.plans.results.onNoLimits", { name: made.name })
    const count = limitedPeople(after.plans)
    return count > 0 ? t("people.plans.results.on", { count }) : t("people.plans.results.onNobody")
  }
  return t("people.plans.results.defaultChanged", { name: defaultName(after) ?? "" })
}

/**
 * The change that undoes a change of the Plans setting: the switch pressed again, keeping the
 * default the server has now, so turning Plans on again never makes a second No limits; or the
 * default it had, keeping whether Plans are on.
 */
export function undoOf(before: PlansOverview, after: PlansOverview): SettingChange {
  return before.enabled !== after.enabled
    ? { enabled: before.enabled, defaultPlan: after.default_plan }
    : { enabled: after.enabled, defaultPlan: before.default_plan }
}

/** Whether a change of the Plans setting was the switch's, so its refusal shows under the switch. */
export function switchedBy(change: SettingChange | undefined, overview: PlansOverview): boolean {
  return change !== undefined && change.enabled !== overview.enabled
}
