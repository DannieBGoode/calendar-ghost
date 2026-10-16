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
  SyncInterval,
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

/** How soon a Plan's rules sync, as an administrator chooses it. */
export function intervalLabel({ t }: I18n, interval: SyncInterval): string {
  return t(`people.plans.interval.${interval}`)
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

function tokenLimit({ t }: I18n, tokens: number | null): string {
  if (tokens === null) return t("people.plans.limits.unlimitedTokens")
  return tokens === 0 ? t("people.plans.limits.noTokens") : t("people.plans.limits.tokens", { count: tokens })
}

/**
 * How a list of a Plan's counts says "No limit" where it starts: a Plan's row starts a line with
 * it, and Change plan's options after the Plan's name.
 */
type NoLimitWords = { rules: MessageKey; all: MessageKey }

const ROW_NO_LIMIT: NoLimitWords = { rules: "people.plans.limits.unlimitedRules", all: "people.plans.limits.unlimited" }
const OPTION_NO_LIMIT: NoLimitWords = { rules: "people.plan.limits.unlimitedRules", all: "people.plan.limits.unlimited" }

/**
 * A Plan's counts: rules, calendar accounts, then Integration Tokens, with "No limit" where a
 * count has none, said once when none has.
 */
function countsList(i18n: I18n, { rules, connected_accounts, integration_tokens }: PlanLimits, noLimit: NoLimitWords): string {
  const { t } = i18n
  if (rules === null && connected_accounts === null && integration_tokens === null) return t(noLimit.all)
  return i18n.format.unitList([
    rules === null ? t(noLimit.rules) : t("people.plans.limits.rules", { count: rules }),
    connected_accounts === null
      ? t("people.plans.limits.unlimitedAccounts")
      : t("people.plans.limits.accounts", { count: connected_accounts }),
    tokenLimit(i18n, integration_tokens),
  ])
}

/** A Plan's counts on its row in People's Plans tab, such as "5 rules, 3 calendar accounts, 2 Integration Tokens". */
export function planLimitsSummary(i18n: I18n, limits: PlanLimits): string {
  return countsList(i18n, limits, ROW_NO_LIMIT)
}

/**
 * A Plan as Change plan offers it, with what it allows, so the administrator need not remember:
 * "Free: 1 rule, 1 calendar account, no Integration Tokens, every 5 minutes".
 */
export function planChoiceLabel(i18n: I18n, { name, limits }: Pick<PlanSummary, "name" | "limits">): string {
  return i18n.t("people.plan.option", {
    name,
    limits: countsList(i18n, limits, OPTION_NO_LIMIT),
    interval: i18n.t(`people.plan.interval.${limits.sync_interval}`),
  })
}

/**
 * Change plan's choice to follow the Default Plan, naming the Plan that is the default now, as
 * "Default plan (Free)"; without one yet, "Default plan".
 */
export function defaultPlanChoice({ t }: I18n, plans: readonly PlanSummary[]): string {
  const current = plans.find((plan) => plan.is_default)
  return current ? t("people.plan.default", { name: current.name }) : t("people.plan.defaultUnnamed")
}

/** Which limit a row of Your plan shows. */
type OwnPlanLimit = "rules" | "accounts" | "tokens" | "sync"

/** One row of Your plan: a limit, how much of it is in use, what counts toward it, and past it, what that means. */
export type OwnPlanRow = {
  limit: OwnPlanLimit
  title: string
  /** How much is in use against the limit, such as "3 of 5 in use"; for the sync row, how soon calendars sync. */
  value: string
  /** What counts toward the limit, in the words of the Plan's editor; null for the sync row. */
  hint: string | null
  /** Past the limit, as after it was lowered: what keeps working and how to make room. Null within it. */
  over: string | null
}

type CountWords = { title: MessageKey; hint: MessageKey; over: MessageKey }

const COUNT_WORDS: Record<Exclude<OwnPlanLimit, "sync">, CountWords> = {
  rules: { title: "settings.ownPlan.rules", hint: "settings.ownPlan.rulesHint", over: "settings.ownPlan.over.rules" },
  accounts: {
    title: "settings.ownPlan.accounts",
    hint: "settings.ownPlan.accountsHint",
    over: "settings.ownPlan.over.accounts",
  },
  tokens: { title: "settings.ownPlan.tokens", hint: "settings.ownPlan.tokensHint", over: "settings.ownPlan.over.tokens" },
}

/**
 * How much of one limit is in use: "No limit, 3 in use" where the Plan sets none, "Not included"
 * where it allows none, "3 of 5 in use" within it, and past it, as after it was lowered, by the
 * count in use: "6 in use, 5 allowed".
 */
function inUse({ t }: I18n, used: number, limit: number | null): string {
  if (limit === null) return t("settings.ownPlan.use.unlimited", { used })
  // A Plan may include no tokens; one lowered to none still counts the tokens kept from before.
  if (limit === 0) return used === 0 ? t("settings.ownPlan.use.none") : t("settings.ownPlan.use.noneOver", { used })
  return used > limit ? t("settings.ownPlan.use.over", { used, limit }) : t("settings.ownPlan.use.within", { used, limit })
}

function countRow(i18n: I18n, limit: keyof typeof COUNT_WORDS, used: number, allowed: number | null): OwnPlanRow {
  const { t } = i18n
  const words = COUNT_WORDS[limit]
  const over = allowed !== null && used > allowed
  return { limit, title: t(words.title), value: inUse(i18n, used, allowed), hint: t(words.hint), over: over ? t(words.over) : null }
}

/**
 * Your plan's rows: rules, calendar accounts, and Integration Tokens, each against its limit, then
 * how soon calendars sync. None when no Plan limits the User.
 */
export function ownPlanRows(i18n: I18n, plan: OwnPlan): OwnPlanRow[] {
  const { limits } = plan
  if (plan.basis !== "plan" || !limits) return []
  return [
    countRow(i18n, "rules", plan.rules_counted, limits.rules),
    countRow(i18n, "accounts", plan.connected_accounts, limits.connected_accounts),
    countRow(i18n, "tokens", plan.integration_tokens, limits.integration_tokens),
    {
      limit: "sync",
      title: i18n.t("settings.ownPlan.interval"),
      value: intervalLabel(i18n, limits.sync_interval),
      hint: null,
      over: null,
    },
  ]
}

/** How each limit a person is over reads, by the count in use: "2 calendar accounts, 1 allowed". */
const OVER_WORDS: Readonly<Record<OverLimit["limit"], MessageKey>> = {
  rules: "people.plan.over.rules",
  connected_accounts: "people.plan.over.accounts",
  integration_tokens: "people.plan.over.tokens",
}

function overLimitText({ t }: I18n, { limit, in_use, allowed }: OverLimit): string {
  // A Plan may include no Integration Tokens; one lowered to none still counts those kept.
  if (limit === "integration_tokens" && allowed === 0) return t("people.plan.over.tokensNone", { count: in_use })
  return t(OVER_WORDS[limit], { count: in_use, allowed })
}

type HeldPlan = NonNullable<PersonPlanOverview["has"]>

/** The Plan a person has, by name, "(default)" when it is theirs as the default. */
function heldPlanText({ t }: I18n, { name, on_default }: HeldPlan, later: boolean): string {
  if (later) return on_default ? t("people.plan.fact.laterDefault", { name }) : t("people.plan.fact.later", { name })
  return on_default ? t("people.plan.fact.default", { name }) : t("people.plan.fact.own", { name })
}

/** Whether no Plan limits this person because they administer, whether or not Plans are on. */
function administers({ basis }: PersonPlanOverview, administrator: boolean): boolean {
  return administrator || basis === "administrator"
}

/**
 * The Plan fact on a person's page: the Plan they have, as the Plans tab counts who has it, "once
 * plans are on" while Plans are off, and each limit they have more of than it allows. An
 * administrator has a Plan as anyone does, but no Plan limits them, whether Plans are on or off.
 */
export function personPlanFact(i18n: I18n, plan: PersonPlanOverview, administrator: boolean): string {
  const { t } = i18n
  const held = plan.has ?? plan.plan
  if (administers(plan, administrator)) {
    return held
      ? t("people.plan.fact.administratorHas", { plan: heldPlanText(i18n, held, false) })
      : t("people.plan.fact.administrator")
  }
  const fact = held ? heldPlanText(i18n, held, plan.basis !== "plan") : t("people.plan.fact.laterNone")
  return plan.over.reduce((text, over) => t("people.plan.fact.over", { fact: text, over: overLimitText(i18n, over) }), fact)
}

/** Whether a person's Plan fact names a limit they are over, and so takes the attention tone. */
export function personPlanOver(plan: PersonPlanOverview, administrator: boolean): boolean {
  return !administers(plan, administrator) && plan.over.length > 0
}
