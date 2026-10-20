import type { I18n } from "@/i18n/translator"

/** User-facing identity. Code identifiers, storage keys, and env vars keep `calendar-sync`. */
export const PRODUCT_NAME = "Calendar Ghost"
export const APP_VERSION = __APP_VERSION__
const REPOSITORY_URL = "https://github.com/DannieBGoode/calendar-ghost"
export const SOURCE_URL = __SOURCE_URL__
export const LICENSE_URL = `${REPOSITORY_URL}/blob/main/LICENSE`
/** The project site's pages built from the repository's docs/ (site/src/docs/pages.ts). */
const DOCS_URL = "https://calendarghost.com/docs"
/** The troubleshooting guide on the project site; it ends with where to ask for more help. */
export const HELP_URL = `${DOCS_URL}/troubleshooting`
/** The Instant Sync guide; its sections' anchors follow the headings in docs/instant-sync.md. */
export const INSTANT_SYNC_HELP_URL = `${DOCS_URL}/instant-sync`
/** The email notifications guide keeps this explicit legacy anchor in docs/troubleshooting.md. */
export const EMAIL_NOTIFICATIONS_HELP_URL = `${HELP_URL}#incident-emails-are-unavailable-or-never-arrive`

export function documentTitle(i18n: I18n, page: string): string {
  return i18n.t("app.documentTitle", { page })
}
