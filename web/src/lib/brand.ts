import type { I18n } from "@/i18n/translator"

/** User-facing identity. Code identifiers, storage keys, and env vars keep `calendar-sync`. */
export const PRODUCT_NAME = "Calendar Ghost"
export const APP_VERSION = __APP_VERSION__
const REPOSITORY_URL = "https://github.com/DannieBGoode/calendar-ghost"
export const SOURCE_URL = __SOURCE_URL__
export const LICENSE_URL = `${REPOSITORY_URL}/blob/main/LICENSE`
/** The troubleshooting guide on the project site; it ends with where to ask for more help. */
export const HELP_URL = "https://calendarghost.com/docs/troubleshooting"
/** The guide's section on incident emails; its anchor follows the heading in docs/troubleshooting.md. */
export const INCIDENT_EMAIL_HELP_URL = `${HELP_URL}#incident-emails-are-unavailable-or-never-arrive`

export function documentTitle(i18n: I18n, page: string): string {
  return i18n.t("app.documentTitle", { page })
}
