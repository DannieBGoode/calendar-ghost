import type { I18n } from "@/i18n/translator"
import type { MessageKey } from "@/i18n/types"
import type {
  OverLimit,
  OwnPlan,
  PersonPlanOverview,
  PlanLimits,
  PlanSummary,
  RegistrationPolicy,
  RuleDetail,
  RuleSummary,
} from "@/lib/api"

/**
 * Whether Your plan shows: only when a Plan limits the User, or for an administrator while other
 * people can join. It stays hidden while Plans are off, and under Only Me, where the only person
 * administers. Only an administrator can read the Registration Policy, so `policy` is undefined
 * for everyone else and while it loads.
 */
export function ownPlanShown(plan: OwnPlan | undefined, policy: RegistrationPolicy | undefined): boolean {
  if (plan?.basis === "plan") return true
  if (plan?.basis === "administrator") return policy !== undefined && policy !== "only_me"
  return false
}

/**
 * Whether a privacy edit, a Pause, or a Disconnect may keep a rule from starting again: only Rule
 * Replacement keeps a rule's place under the rule limit, and the User has more rules counted than
 * their Plan allows (ADR 0038).
 */
export function planWarning(plan: OwnPlan | undefined): boolean {
  return plan?.over_rule_limit === true
}

/** The refusal Start would meet, or null when the rule may start; a refused Start shows the same text. */
export function startRefusal(
  { t }: I18n,
  { can_start, rule_limit }: Pick<RuleDetail, "can_start" | "rule_limit">,
): string | null {
  if (can_start) return null
  return rule_limit === null
    ? t("common.apiError.plan_limit_reached")
    : t("common.apiError.plan_limit_reached_rules", { count: rule_limit })
}

/**
 * The refusal Start would meet for a previewed rule, read from Your plan where a page has no
 * `can_start`, such as the Rules list: once the rules counted reach the rule limit, a previewed
 * rule cannot start unless it keeps a replaced rule's place. Null when it may start, and while
 * the Plan is unknown, since Start still checks.
 */
export function previewedStartRefusal(
  i18n: I18n,
  plan: OwnPlan | undefined,
  { state, keeps_place }: Pick<RuleSummary, "state" | "keeps_place">,
): string | null {
  const limit = plan?.limits?.rules
  if (state !== "dry_run_validated" || keeps_place || plan === undefined || typeof limit !== "number") return null
  return startRefusal(i18n, { can_start: plan.rules_counted < limit, rule_limit: limit })
}

/**
 * Whether a Plan limits nothing: no limit on any count, and instant sync. The Plan the server makes
 * when Plans turn on with no default is one, so whoever has it is not limited.
 */
export function limitsNothing({ rules, connected_accounts, integration_tokens, sync_interval }: PlanLimits): boolean {
  return rules === null && connected_accounts === null && integration_tokens === null && sync_interval === "instant"
}

/** How many people Plans limit while on: those each Plan limits, except a Plan that limits nothing. */
export function limitedPeople(plans: readonly PlanSummary[]): number {
  return plans.reduce((total, plan) => (limitsNothing(plan.limits) ? total : total + plan.limited_people), 0)
}

/** How each limit a person is over reads, by the count in use: "2 calendar accounts, 1 allowed". */
const OVER_WORDS: Readonly<Record<OverLimit["limit"], MessageKey>> = {
  rules: "people.plan.over.rules",
  connected_accounts: "people.plan.over.accounts",
  integration_tokens: "people.plan.over.tokens",
}

/** One limit a person is over, or would be under another Plan: "2 calendar accounts, 1 allowed". */
export function overLimitText({ t }: I18n, { limit, in_use, allowed }: OverLimit): string {
  // A Plan may include no Integration Tokens; one lowered to none still counts those kept.
  if (limit === "integration_tokens" && allowed === 0) return t("people.plan.over.tokensNone", { count: in_use })
  return t(OVER_WORDS[limit], { count: in_use, allowed })
}

type HeldPlan = NonNullable<PersonPlanOverview["has"]>

/**
 * A Plan by name, "(default)" when it is someone's as the default: "Free (default)". People's Plan
 * filter names the default Plan the same way.
 */
export function heldPlanName({ t }: I18n, { name, on_default }: Pick<HeldPlan, "name" | "on_default">): string {
  return on_default ? t("people.plan.held.default", { name }) : name
}

/** Whether no Plan limits this person because they administer, whether or not Plans are on. */
function administers({ basis }: PersonPlanOverview, administrator: boolean): boolean {
  return administrator || basis === "administrator"
}

/**
 * A chip beside a person's Plan: "Default" when they have it as the default, "Over a limit" in
 * Attention Ochre while Plans are on and they have more than it allows ("Would be over", neutral,
 * while off), with each limit in words as its `detail`, and "Not limited" for an administrator.
 */
export type PlanChip = { id: "default" | "over" | "notLimited"; text: string; tone: "neutral" | "attention"; detail?: string }

/** The chips beside a person's Plan, in People's Plan column and on their Plan card, in that order. */
export function heldPlanChips(i18n: I18n, plan: PersonPlanOverview, administrator: boolean): PlanChip[] {
  const { t } = i18n
  const chips: PlanChip[] = []
  if (plan.has?.on_default) chips.push({ id: "default", text: t("people.plan.chips.default"), tone: "neutral" })
  if (administers(plan, administrator)) {
    chips.push({ id: "notLimited", text: t("people.plan.chips.notLimited"), tone: "neutral" })
    return chips
  }
  if (plan.over.length > 0) {
    const enforced = plan.basis === "plan"
    chips.push({
      id: "over",
      text: t(enforced ? "people.plan.chips.over" : "people.plan.chips.wouldBeOver"),
      tone: enforced ? "attention" : "neutral",
      detail: i18n.format.list(plan.over.map((over) => overLimitText(i18n, over))),
    })
  }
  return chips
}
