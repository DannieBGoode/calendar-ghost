import { INSTANT_SYNC_HELP_URL } from "@/lib/brand"

/** Whether Instant Sync runs a User's rules, as the server decides it (`Availability` in domain/watches.py). */
type Availability = "on" | "off_by_user" | "not_in_plan" | "no_public_address" | "not_reaching"

const AVAILABILITIES: readonly Availability[] = ["on", "off_by_user", "not_in_plan", "no_public_address", "not_reaching"]

/** What keeps the switch from working for the User; `unknown` for a reason a later server sends. */
type InstantSyncBlock = Exclude<Availability, "on" | "off_by_user"> | "unknown"

/** Why a rule syncs as it does, as the server names it (`CadenceReason` in domain/watches.py). */
type CadenceReason =
  | "instant"
  | "not_watchable"
  | "waiting_for_provider"
  | "off_by_user"
  | "not_in_plan"
  | "no_public_address"
  | "not_reaching"

const REASONS: readonly CadenceReason[] = [
  "instant",
  "not_watchable",
  "waiting_for_provider",
  "off_by_user",
  "not_in_plan",
  "no_public_address",
  "not_reaching",
]

/**
 * Each reason's section of docs/instant-sync.md; tests/test_instant_sync_docs.py checks that the
 * guide holds them. A reason the User chose needs no explanation, so it has none.
 */
const REASON_ANCHORS: Partial<Record<CadenceReason, string>> = {
  not_watchable: "this-calendar-cannot-be-watched",
  waiting_for_provider: "waiting-for-the-provider",
  not_in_plan: "not-in-your-plan",
  no_public_address: "no-public-https-address",
  not_reaching: "providers-cannot-reach-the-installation",
}

/** How soon an enabled rule syncs, as its page says it. */
type RuleCadence = {
  instant: boolean
  /** Why it syncs on its schedule; null when it syncs instantly or the reason is not known here. */
  reason: Exclude<CadenceReason, "instant"> | null
  minutes: number
  helpUrl: string | null
}

/** Why the Instant sync switch cannot be used, or null when it is the User's to turn on or off. */
export function instantSyncBlock(availability: string): InstantSyncBlock | null {
  const known = AVAILABILITIES.find((each) => each === availability)
  if (known === undefined) return "unknown"
  return known === "on" || known === "off_by_user" ? null : known
}

/** The Instant Sync guide's section on `anchor`; null without one. */
export function instantSyncHelpUrl(anchor: string | null | undefined): string | null {
  return anchor ? `${INSTANT_SYNC_HELP_URL}#${anchor}` : null
}

export function ruleCadence(detail: { effective_cadence: string; poll_every_minutes: number }): RuleCadence {
  const reason = REASONS.find((each) => each === detail.effective_cadence)
  const minutes = detail.poll_every_minutes
  if (reason === "instant") return { instant: true, reason: null, minutes, helpUrl: null }
  const anchor = reason === undefined ? undefined : REASON_ANCHORS[reason]
  return { instant: false, reason: reason ?? null, minutes, helpUrl: instantSyncHelpUrl(anchor) }
}
