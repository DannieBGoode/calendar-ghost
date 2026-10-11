import type { I18n } from "@/i18n/translator"
import type { CalendarProvider, InstallationHint, ServerProblem } from "@/lib/api"
import { HELP_URL } from "@/lib/brand"

/** Why a provider call failed (ADR 0031), as the server names it. */
export type Cause = NonNullable<ServerProblem["cause"]>

const CAUSES: readonly Cause[] = [
  "api_disabled",
  "quota_exceeded",
  "oauth_client_invalid",
  "access_revoked",
  "calendar_forbidden",
  "calendar_not_found",
  "rate_limited",
  "temporary",
  "unknown",
]

/**
 * The Causes only the installation's administrator can fix, as `causes.ADMINISTRATOR_CAUSES` names
 * them. Each provider says where its troubleshooting guide explains them (GET /api/v1/providers).
 */
const ADMINISTRATOR_CAUSES: ReadonlySet<Cause> = new Set(["api_disabled", "quota_exceeded", "oauth_client_invalid"])

/** Causes the User has nothing to do about: Calendar Ghost tries again by itself. */
const FIXES_ITSELF: ReadonlySet<Cause> = new Set(["rate_limited", "temporary"])

/** A problem's Cause; one a later server sends that this version does not know reads as unknown. */
export function causeOf(problem: Pick<ServerProblem, "cause">): Cause | null {
  const cause = problem.cause
  // A server from before Causes sends none.
  if (!cause) return null
  return CAUSES.includes(cause) ? cause : "unknown"
}

/** Whether only the installation's registration with its provider, so its administrator, can fix it. */
export function isAdministratorCause(cause: Cause | null): boolean {
  return cause !== null && ADMINISTRATOR_CAUSES.has(cause)
}

/** Whether Calendar Ghost tries again by itself, with nothing for anyone to do. */
export function fixesItself(cause: Cause | null): boolean {
  return cause !== null && FIXES_ITSELF.has(cause)
}

/** "Likely cause: …", in plain words. */
export function causeText(i18n: I18n, cause: Cause): string {
  return i18n.t("people.cause.label", { cause: i18n.t(`people.cause.${cause}`) })
}

/**
 * The troubleshooting section for an administrator's Cause, where the provider that raised it says;
 * none for a User's own Cause, or when that provider is not configured here.
 */
export function howToFixUrl(cause: Cause | null, provider: CalendarProvider | null): string | null {
  if (!isAdministratorCause(cause) || cause === null || !provider) return null
  const anchors: Partial<Record<Cause, string>> = provider.cause_anchors
  const anchor = anchors[cause]
  return anchor === undefined ? null : troubleshootingUrl(anchor)
}

export function troubleshootingUrl(anchor: string): string {
  return `${HELP_URL}#${anchor}`
}

/**
 * When a Cause that fixes itself was last tried and when it is tried again, as far as the server
 * knows; null for any other Cause, or when it knows neither.
 */
export function retryTiming(i18n: I18n, problem: ServerProblem, nextPassAt: string | null, now: number): string | null {
  if (!fixesItself(causeOf(problem))) return null
  const parts = [
    problem.last_tried_at && i18n.t("people.cause.lastTried", { relative: i18n.format.relative(problem.last_tried_at, now) }),
    nextPassAt && i18n.t("people.cause.triesAgain", { relative: i18n.format.relative(nextPassAt, now) }),
  ].filter((part): part is string => Boolean(part))
  return parts.length > 0 ? parts.join(" ") : null
}

/** An Installation Hint in one sentence, with how many people it affects. */
export function hintText(i18n: I18n, hint: InstallationHint): string {
  const count = hint.users
  switch (hint.kind) {
    case "testing_mode":
      return i18n.t("people.health.hints.testingMode", { count })
    case "unrecognized":
      return i18n.t("people.health.hints.unrecognized", { count })
    default:
      return i18n.t("people.health.hints.shared", { count, cause: i18n.t(`people.cause.${causeOf(hint) ?? "unknown"}`) })
  }
}

/** Causes the problem's own words already state: a lapsed grant, or a provider limiting requests. */
const STATED_BY_PROBLEM: ReadonlySet<Cause> = new Set(["access_revoked", "rate_limited", "temporary"])

/** Whether "Likely cause" tells the reader something the problem does not already say. */
export function causeAddsToProblem(cause: Cause | null): cause is Cause {
  return cause !== null && !STATED_BY_PROBLEM.has(cause)
}
