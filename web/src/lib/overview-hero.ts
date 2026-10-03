import type { OverviewTone } from "./overview-health"

/** What the ghost says. It reacts to the state in a few words; the hero copy carries the facts. */
export type HeroCallout = { title: string; detail?: string }

/**
 * The ghost's lines for each state. A stopped ghost calls out for help, one line at a time around
 * it; reduced motion keeps the first line still.
 */
const CALLOUTS: Record<OverviewTone, readonly HeroCallout[]> = {
  healthy: [{ title: "All good!", detail: "Your calendars are in sync." }],
  review: [{ title: "Almost all good" }],
  stopped: [{ title: "Help!" }, { title: "I need a hand" }, { title: "Anyone there?" }, { title: "Over here!" }],
  waiting: [{ title: "Hang tight…" }],
  paused: [{ title: "Taking a break" }],
  setup: [{ title: "Ready when you are!" }],
}

export function overviewHeroCallouts(tone: OverviewTone): readonly HeroCallout[] {
  return CALLOUTS[tone]
}
