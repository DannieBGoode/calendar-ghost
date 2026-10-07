import { docPagePath } from "./docs/pages"

export const SITE_URL = "https://calendarghost.com"
export const REPO_URL = "https://github.com/DannieBGoode/calendar-ghost"
/** The self-hosting guide, rendered on this site from docs/self-hosting.md (docs/pages.ts). */
export const GUIDE_URL = docPagePath("self-hosting")
export const LICENSE_URL = `${REPO_URL}/blob/main/LICENSE`
export const TRADEMARKS_URL = `${REPO_URL}/blob/main/TRADEMARKS.md`
export const CHANGELOG_URL = `${REPO_URL}/blob/main/CHANGELOG.md`
/** The documentation folder, as GitHub lists it. */
export const DOCS_URL = `${REPO_URL}/tree/main/docs`

const DOCS = `${REPO_URL}/blob/main`
/** Section 6 of the self-hosting guide: Integration Tokens, the status API, and the MCP server.
 * The anchor is GitHub's slug for the heading, which the rendered page keeps. */
export const INTEGRATIONS_URL = `${GUIDE_URL}#6-connect-monitors-and-agents`

/** The documentation that proves each trust claim, in the order of `trust.cards`. A unit test
 * checks that every file and heading anchor exists in the repository (for a page rendered here,
 * in the file it is built from). */
export const TRUST_DOCS = [
  `${DOCS}/docs/sync-model.md#reconciliation`,
  `${DOCS}/README.md#3-start-the-service`,
  `${DOCS}/docs/data-ownership.md`,
  `${DOCS}/docs/sync-model.md#loop-prevention`,
  `${DOCS}/docs/sync-model.md#recurrence`,
  `${DOCS}/README.md#current-capabilities`,
  `${DOCS}/docs/data-ownership.md#what-can-leave-the-machine`,
  INTEGRATIONS_URL,
] as const
