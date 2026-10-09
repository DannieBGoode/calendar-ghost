// Visits are counted with Umami Cloud: no cookies, nothing that identifies a visitor, and no
// tracking across sites. The tracker script and the endpoint it posts to are served from this
// site's own origin by the Worker (worker/index.ts), so the page still contacts no other host. The
// neutral path keeps ad-blocker lists that name Umami or "analytics" from dropping the count.
// The tracker loads only when the build sets PUBLIC_UMAMI_WEBSITE_ID (astro.config.mjs).

export const ANALYTICS_PREFIX = "/lantern"
export const TRACKER_PATH = `${ANALYTICS_PREFIX}/script.js`
/** Umami's tracker posts to `<data-host-url>/api/send`. */
export const COLLECT_PATH = `${ANALYTICS_PREFIX}/api/send`
/** Visits count only here: not on localhost, in preview builds, or on a fork's own domain. */
export const ANALYTICS_DOMAIN = "calendarghost.com"

/** The clicks Umami counts, by `data-umami-event` name. A `data-umami-event-place` attribute
 * tells apart the same click in different places on the page. */
export const ANALYTICS_EVENTS = {
  github: "github-click",
  copyCommands: "copy-commands",
  guide: "guide-open",
} as const
