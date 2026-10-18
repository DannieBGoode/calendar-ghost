import type { I18n } from "@/i18n/translator"
import { capitalized } from "@/lib/activity-names"
import type { PlanLimits, PlanSummary } from "@/lib/api"

/**
 * The words of a Plan's side panel: who has the Plan and what it allows, in one line under its
 * name; and each Plan's limits in short, where Change plan offers it.
 */

function countWords({ t }: I18n, { rules, connected_accounts, integration_tokens }: PlanLimits): string[] {
  return [
    rules === null ? t("people.plans.panel.rulesUnlimited") : t("people.plans.panel.rules", { count: rules }),
    connected_accounts === null
      ? t("people.plans.panel.accountsUnlimited")
      : t("people.plans.panel.accounts", { count: connected_accounts }),
    integration_tokens === null
      ? t("people.plans.panel.tokensUnlimited")
      : integration_tokens === 0
        ? t("people.plans.panel.tokensNone")
        : t("people.plans.panel.tokens", { count: integration_tokens }),
  ]
}

/**
 * What a Plan allows, in a sentence: "1 active rule, 1 calendar account, no Integration Tokens,
 * every 5 minutes.", or, with no limit on any count, "Unlimited, with Instant sync."
 */
export function planAllowsSentence(i18n: I18n, limits: PlanLimits): string {
  const speed = i18n.t(`people.plans.panel.speed.${limits.sync_interval}`)
  const { rules, connected_accounts, integration_tokens } = limits
  if (rules === null && connected_accounts === null && integration_tokens === null) {
    return i18n.t("people.plans.panel.unlimited", { speed })
  }
  return capitalized(i18n, i18n.t("people.plans.panel.allows", { limits: i18n.format.unitList([...countWords(i18n, limits), speed]) }))
}

/** The line under a Plan's name in its panel: who has it, then what it allows. */
export function planPanelMeta(i18n: I18n, { name, people, limits }: Pick<PlanSummary, "name" | "people" | "limits">): string {
  const holders =
    people === 0 ? i18n.t("people.plans.panel.holdersNone", { name }) : i18n.t("people.plans.panel.holders", { count: people, name })
  return i18n.t("people.plans.panel.meta", { holders, allows: planAllowsSentence(i18n, limits) })
}

/** Each count's word or two in a short summary: "5 rules", "unlimited accounts", "no tokens". */
function shortCounts({ t }: I18n, { rules, connected_accounts, integration_tokens }: PlanLimits): string[] {
  if (rules === null && connected_accounts === null && integration_tokens === null) return [t("people.plans.change.limits.unlimited")]
  return [
    rules === null ? t("people.plans.change.limits.rulesUnlimited") : t("people.plans.change.limits.rules", { count: rules }),
    connected_accounts === null
      ? t("people.plans.change.limits.accountsUnlimited")
      : t("people.plans.change.limits.accounts", { count: connected_accounts }),
    integration_tokens === null
      ? t("people.plans.change.limits.tokensUnlimited")
      : integration_tokens === 0
        ? t("people.plans.change.limits.tokensNone")
        : t("people.plans.change.limits.tokens", { count: integration_tokens }),
  ]
}

/**
 * A Plan's limits in short, as a line beside its name in Change plan: "1 rule, 1 account, no
 * tokens, every 5 min", or, with no limit on any count, "Unlimited, Instant".
 */
export function planLimitsSummary(i18n: I18n, limits: PlanLimits): string {
  const speed = i18n.t(`people.plans.change.limits.speed.${limits.sync_interval}`)
  return capitalized(i18n, i18n.format.unitList([...shortCounts(i18n, limits), speed]))
}
