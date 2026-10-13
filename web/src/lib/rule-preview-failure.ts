import { apiErrorMessage } from "@/i18n/api-errors"
import type { I18n } from "@/i18n/translator"
import { needsReauthorization } from "@/lib/account-summary"
import { ApiError, type ConnectedAccount } from "@/lib/api"

/** Why a preview did not finish, sorted by the one step that helps. */
export type PreviewFailure =
  | { kind: "lapsed"; account: ConnectedAccount | undefined }
  | { kind: "unavailable"; provider: string | null }
  | { kind: "changed" }
  | { kind: "syncing" }
  | { kind: "failed"; message: string }

const LAPSED_KINDS = ["authentication", "authorization"]

/** The rule's own account that lapsed, from the provider that refused; never another one. */
function lapsedAccount(accounts: ConnectedAccount[], ruleAccounts: readonly string[], provider: string | null) {
  const ours = new Set(ruleAccounts)
  return accounts.find(
    (account) => ours.has(account.id) && needsReauthorization(account) && (!provider || account.provider === provider),
  )
}

export function previewFailure(
  i18n: I18n,
  error: unknown,
  { ruleState, ruleAccounts, accounts }: { ruleState: string | undefined; ruleAccounts: readonly string[]; accounts: ConnectedAccount[] },
): PreviewFailure {
  if (error instanceof ApiError && error.code === "rule_not_executable") {
    return ruleState === "enabled" ? { kind: "syncing" } : { kind: "changed" }
  }
  if (error instanceof ApiError && error.code === "provider_failed") {
    const failureKind = typeof error.params.kind === "string" ? error.params.kind : ""
    const provider = typeof error.params.provider === "string" ? error.params.provider : null
    if (LAPSED_KINDS.includes(failureKind)) return { kind: "lapsed", account: lapsedAccount(accounts, ruleAccounts, provider) }
    return { kind: "unavailable", provider }
  }
  return { kind: "failed", message: apiErrorMessage(i18n, error) }
}
