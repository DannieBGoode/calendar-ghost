import type { I18n } from "@/i18n/translator"
import type { RulePolicyPayload } from "@/lib/api"

/**
 * The title `domain/services.py` writes to every Busy-Only projection. Google Calendar receives it
 * in English whatever the UI language, so it is a message parameter, never translated.
 */
export const BUSY_TITLE = "Busy"

/** What the destination shows of each event, and who sees it when details are copied. */
export function privacyHint(i18n: I18n, privacy: RulePolicyPayload["privacy_policy"], destination: string): string {
  if (privacy === "busy_only") return i18n.t("rules.policy.privacyHint.busyOnly", { title: BUSY_TITLE })
  return i18n.t("rules.policy.privacyHint.copyDetails", { destination })
}
