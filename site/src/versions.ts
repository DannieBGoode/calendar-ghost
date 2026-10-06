// Every version of the landing page and every iteration of it, for the team's own index at
// /versions. A new iteration is a new route (never a change to an old one): add its page, then
// append it here with the commit that added it.
//
// This index, the /versions page, and the small "Versions" link on iteration pages are internal
// tools, not public copy, so their words live here instead of in i18n/en.ts (AGENTS.md, "Landing
// page"). None of it is indexed or in the sitemap.

/**
 * Where an iteration stands: `current` is the live page, a `candidate` is still in the running,
 * a `rejected` one stays for comparison but is not to be built on, and a `discarded` one has no
 * route any more: its entry stays, to see with git at the commit that added it.
 */
export type IterationStatus = "current" | "candidate" | "rejected" | "discarded"

export interface Iteration {
  name: string
  status: IterationStatus
  /** The route, starting with "/" (for a discarded iteration, the route it had). */
  path: string
  /** One line on what it tries. */
  tries: string
  /** When it was added, as YYYY-MM-DD. */
  date: string
  /** The short SHA of the commit that added it. */
  commit: string
}

export interface Version {
  name: string
  iterations: readonly Iteration[]
}

export const VERSIONS: readonly Version[] = [
  {
    name: "Home",
    iterations: [
      {
        name: "Iteration 1 (production)",
        status: "current",
        path: "/",
        tries: "A centered two-line headline over the full Wide Reveal week; the live page.",
        date: "2026-10-05",
        commit: "747b4e7",
      },
      {
        name: "Hero A: a quieter /bold",
        status: "candidate",
        path: "/home/hero-a",
        tries: "Pitch in a narrow column; a larger, cropped week runs off the right edge, sweeping left first so Busy shows at once.",
        date: "2026-10-05",
        commit: "b8b0682",
      },
      {
        name: "Hero B: one event, big",
        status: "candidate",
        path: "/home/hero-b",
        tries: "No week: the ghost carries one large Dentist card to Work, where it lands as Busy and the guest and link stay behind.",
        date: "2026-10-05",
        commit: "c4324a5",
      },
      {
        name: "Hero C: the headline is the demo",
        status: "discarded",
        path: "/home/hero-c",
        tries: "\"Work sees [Dentist]\": the ghost draws Busy over a real event in the headline, with two days of the week as proof.",
        date: "2026-10-05",
        commit: "a7d8db3",
      },
      {
        name: "Hero A2: A, cleaner",
        status: "candidate",
        path: "/home/hero-a2",
        tries: "A's copy column beside a calmer week inside the page: three events, a plain Busy, lighter lines, every control on screen.",
        date: "2026-10-05",
        commit: "ffdf41b",
      },
      {
        name: "Hero B2: one event, quieter",
        status: "candidate",
        path: "/home/hero-b2",
        tries: "B's carry at a calmer scale: a compact Dentist card and three hours of Work on one soft surface; it plays once, then rests on Busy.",
        date: "2026-10-05",
        commit: "9d55fab",
      },
      {
        name: "Hero D: the same event, with and without",
        status: "rejected",
        path: "/home/hero-d",
        tries: "After littleplains: Sam's Dentist as work sees it without Calendar Ghost (every detail) and with it, where the rule's lines tick in until only Busy is left.",
        date: "2026-10-06",
        commit: "4341630",
      },
      {
        name: "Hero E: a node diagram",
        status: "candidate",
        path: "/home/hero-e",
        tries: "After littleplains' diagram: an event's parts in outlined pills, hairlines through one outlined ghost to Sam's calendars, and small coloured segments that show what crosses over and what stops.",
        date: "2026-10-06",
        commit: "07ccbf1",
      },
      {
        name: "Hero E2: many calendars into one",
        status: "candidate",
        path: "/home/hero-e2",
        tries: "Hero E's diagram telling the real story: Sam's calendars in their own colours flow through the ghost and land on one Work day as indigo Busy blocks.",
        date: "2026-10-06",
        commit: "88cb76c",
      },
      {
        name: "Hero E3: the diagram, semantically right",
        status: "candidate",
        path: "/home/hero-e3",
        tries: "Left to right: Sam's calendars as pills, the ghost character at the hub, and a day on the right. Event chips go through the ghost; bound for Work, titles drop there (kept by the ghost, struck through) and land as Busy at their time; a switch shows Sam's Personal calendar instead, every title kept.",
        date: "2026-10-06",
        commit: "0000000",
      },
    ],
  },
  {
    name: "Bold",
    iterations: [
      {
        name: "Bold",
        status: "candidate",
        path: "/bold",
        tries: "The home page's structure with a stronger hand: big type, a split hero, a night band, a poster footer.",
        date: "2026-10-05",
        commit: "11d94ef",
      },
    ],
  },
  {
    name: "Journey",
    iterations: [
      {
        name: "Journey",
        status: "candidate",
        path: "/journey",
        tries: "One story: the ghost carries Sam's Dentist appointment down the page, and every section is a stop.",
        date: "2026-10-05",
        commit: "b564214",
      },
    ],
  },
]

/** States changed in place before this convention existed, to see with `git worktree add`. */
export const EARLIER_STATES: readonly { commit: string; what: string }[] = [
  { commit: "20ec416", what: "The first page, before the redesign" },
  { commit: "92f5823", what: "After phase 1: the ghost character, the demos, the app mockups" },
  { commit: "579b106", what: "After phase 1b: /bold and the first round of fixes" },
  { commit: "3b9dc7d", what: "After phase 4: /journey, How it works switch, one Dentist time" },
]

/** The index's own route. */
export const VERSIONS_PATH = "/versions"

/** Whether the iteration still has its route (every status but `discarded`). */
export function isLive(iteration: Iteration): boolean {
  return iteration.status !== "discarded"
}

/** Every route that is not the production page: not indexed, kept out of the sitemap, and given
 * the small link back to the index. */
export const NON_PRODUCTION_PATHS: readonly string[] = [
  VERSIONS_PATH,
  ...VERSIONS.flatMap((version) => version.iterations.filter(isLive).map((iteration) => iteration.path)).filter(
    (path) => path !== "/",
  ),
]

/** How the index names each status. */
export const STATUS_LABELS: Record<IterationStatus, string> = {
  current: "Current",
  candidate: "Candidate",
  rejected: "Rejected",
  discarded: "Discarded",
}

/** What a discarded entry shows instead of a link. */
export const VIEW_WITH_GIT = "View with git:"

/** The command that checks out the commit that added an iteration, beside your work. */
export function worktreeCommand(commit: string): string {
  return `git worktree add ../calendar-ghost-${commit} ${commit}`
}

/** The "Versions" link's words. */
export const VERSIONS_LINK_LABEL = "Versions"
