import type { I18n } from "@/i18n/translator"
import type { MessageKey } from "@/i18n/types"
import type { OwnPlan, PersonPlan, PlanLimits, RegistrationPolicy, RuleDetail, RuleSummary, SyncInterval } from "@/lib/api"

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

/** How soon a Plan's rules sync, as an administrator chooses it. */
export function intervalLabel({ t }: I18n, interval: SyncInterval): string {
  return t(`people.plans.interval.${interval}`)
}

function tokenLimit({ t }: I18n, tokens: number | null): string {
  if (tokens === null) return t("people.plans.limits.unlimitedTokens")
  return tokens === 0 ? t("people.plans.limits.noTokens") : t("people.plans.limits.tokens", { count: tokens })
}

/** A Plan's counts on its row in People's Plans tab: rules, calendar accounts, then Integration Tokens. */
export function planLimitsSummary(i18n: I18n, { rules, connected_accounts, integration_tokens }: PlanLimits): string {
  const { t } = i18n
  return i18n.format.unitList([
    rules === null ? t("people.plans.limits.unlimitedRules") : t("people.plans.limits.rules", { count: rules }),
    connected_accounts === null
      ? t("people.plans.limits.unlimitedAccounts")
      : t("people.plans.limits.accounts", { count: connected_accounts }),
    tokenLimit(i18n, integration_tokens),
  ])
}

/** How Your plan words one count: with no limit, within the limit, and past it. */
type UseWords = { unlimited: MessageKey; within: MessageKey; over: MessageKey }

const RULE_USE: UseWords = {
  unlimited: "settings.ownPlan.rulesUnlimited",
  within: "settings.ownPlan.rules",
  over: "settings.ownPlan.rulesOver",
}
const ACCOUNT_USE: UseWords = {
  unlimited: "settings.ownPlan.accountsUnlimited",
  within: "settings.ownPlan.accounts",
  over: "settings.ownPlan.accountsOver",
}
const TOKEN_USE: UseWords = {
  unlimited: "settings.ownPlan.tokensUnlimited",
  within: "settings.ownPlan.tokens",
  over: "settings.ownPlan.tokensOver",
}

/**
 * One count against its limit: "3 of 5 rules counted", whose noun follows the limit, reads right
 * only within it. Past it, as after a limit is lowered, "6 rules counted (5 allowed)" follows the
 * count in use.
 */
function limitUse({ t }: I18n, words: UseWords, used: number, limit: number | null): string {
  if (limit === null) return t(words.unlimited, { count: used })
  return used > limit ? t(words.over, { count: used, limit }) : t(words.within, { used, count: limit })
}

function tokenUse(i18n: I18n, used: number, limit: number | null): string {
  // A Plan may offer no tokens; one lowered to none still counts the tokens kept from before.
  if (limit === 0 && used === 0) return i18n.t("settings.ownPlan.noTokens")
  return limitUse(i18n, TOKEN_USE, used, limit)
}

/**
 * Your plan's one line, such as "Family: 3 of 5 rules counted, 2 of 3 calendar accounts, 1 of 2
 * tokens, instant sync included". Null when no Plan limits the User, so there is none to name.
 */
export function ownPlanSummary(i18n: I18n, plan: OwnPlan): string | null {
  const { plan: applied, limits } = plan
  if (applied === null || limits === null) return null
  const { t } = i18n
  return t("settings.ownPlan.summary", {
    plan: t(applied.on_default ? "settings.ownPlan.nameDefault" : "settings.ownPlan.name", { name: applied.name }),
    rules: limitUse(i18n, RULE_USE, plan.rules_counted, limits.rules),
    accounts: limitUse(i18n, ACCOUNT_USE, plan.connected_accounts, limits.connected_accounts),
    tokens: tokenUse(i18n, plan.integration_tokens, limits.integration_tokens),
    cadence: plan.instant
      ? t("settings.ownPlan.cadence.instant")
      : t("settings.ownPlan.cadence.every", { count: plan.poll_every_minutes }),
  })
}

/**
 * The Plan fact on a person's page: the Plan that limits them, the one that will once Plans are
 * on, or that no Plan limits an administrator, with the Plan they were given if any. An
 * administrator reads so whether Plans are on or off, since no Plan ever limits them.
 */
export function personPlanFact({ t }: I18n, { basis, plan, assigned }: PersonPlan, administrator: boolean): string {
  if (administrator || basis === "administrator") {
    return assigned
      ? t("people.plan.fact.administratorAssigned", { name: assigned.name })
      : t("people.plan.fact.administrator")
  }
  if (basis === "plan" && plan) {
    return plan.on_default
      ? t("people.plan.fact.default", { name: plan.name })
      : t("people.plan.fact.own", { name: plan.name })
  }
  return assigned ? t("people.plan.fact.later", { name: assigned.name }) : t("people.plan.fact.laterDefault")
}
