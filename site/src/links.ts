export const SITE_URL = "https://calendarghost.com"
export const REPO_URL = "https://github.com/DannieBGoode/calendar-ghost"
export const GUIDE_URL = `${REPO_URL}/blob/main/docs/self-hosting.md`
export const LICENSE_URL = `${REPO_URL}/blob/main/LICENSE`
export const TRADEMARKS_URL = `${REPO_URL}/blob/main/TRADEMARKS.md`

const DOCS = `${REPO_URL}/blob/main`
/** Section 6 of the self-hosting guide: Integration Tokens, the status API, and the MCP server. */
export const INTEGRATIONS_URL = `${DOCS}/docs/self-hosting.md#6-connect-monitors-and-agents`

/** The documentation that proves each trust claim, in the order of `trust.cards`. A unit test
 * checks that every file and heading anchor exists in the repository. */
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
