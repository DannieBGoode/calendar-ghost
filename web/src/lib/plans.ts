import type { I18n } from "@/i18n/translator"
import type { OwnPlan, PersonPlan, PlanLimits, RegistrationPolicy, RuleDetail, SyncInterval } from "@/lib/api"

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

/** How soon a Plan's rules sync, as an administrator chooses it. */
export function intervalLabel({ t }: I18n, interval: SyncInterval): string {
  return t(`settings.plans.interval.${interval}`)
}

function tokenLimit({ t }: I18n, tokens: number | null): string {
  if (tokens === null) return t("settings.plans.limits.unlimitedTokens")
  return tokens === 0 ? t("settings.plans.limits.noTokens") : t("settings.plans.limits.tokens", { count: tokens })
}

/** A Plan's counts on its Administration row: rules, calendar accounts, then Integration Tokens. */
export function planLimitsSummary(i18n: I18n, { rules, connected_accounts, integration_tokens }: PlanLimits): string {
  const { t } = i18n
  return i18n.format.unitList([
    rules === null ? t("settings.plans.limits.unlimitedRules") : t("settings.plans.limits.rules", { count: rules }),
    connected_accounts === null
      ? t("settings.plans.limits.unlimitedAccounts")
      : t("settings.plans.limits.accounts", { count: connected_accounts }),
    tokenLimit(i18n, integration_tokens),
  ])
}

function ruleUse({ t }: I18n, used: number, limit: number | null): string {
  return limit === null
    ? t("settings.ownPlan.rulesUnlimited", { count: used })
    : t("settings.ownPlan.rules", { used, count: limit })
}

function accountUse({ t }: I18n, used: number, limit: number | null): string {
  return limit === null
    ? t("settings.ownPlan.accountsUnlimited", { count: used })
    : t("settings.ownPlan.accounts", { used, count: limit })
}

function tokenUse({ t }: I18n, used: number, limit: number | null): string {
  if (limit === null) return t("settings.ownPlan.tokensUnlimited", { count: used })
  // A Plan may offer no tokens; one lowered to none still counts the tokens kept from before.
  if (limit === 0 && used === 0) return t("settings.ownPlan.noTokens")
  return t("settings.ownPlan.tokens", { used, count: limit })
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
    rules: ruleUse(i18n, plan.rules_counted, limits.rules),
    accounts: accountUse(i18n, plan.connected_accounts, limits.connected_accounts),
    tokens: tokenUse(i18n, plan.integration_tokens, limits.integration_tokens),
    cadence: plan.instant
      ? t("settings.ownPlan.cadence.instant")
      : t("settings.ownPlan.cadence.every", { count: plan.poll_every_minutes }),
  })
}

/**
 * The Plan fact on a person's page: the Plan that limits them, the one that will once Plans are
 * on, or that no Plan limits an administrator, with the Plan they were given if any.
 */
export function personPlanFact({ t }: I18n, { basis, plan, assigned }: PersonPlan): string {
  if (basis === "administrator") {
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
