/** User-facing identity. Code identifiers, storage keys, and env vars keep `calendar-sync`. */
export const PRODUCT_NAME = "Calendar Ghost"
export const TAGLINE = "Your busy time, everywhere it needs to be."
export const APP_VERSION = __APP_VERSION__

export function documentTitle(page: string): string {
  return `${page} – ${PRODUCT_NAME}`
}
