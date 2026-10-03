import type { OverviewTone } from "./overview-health"

export type HeroCallout = { title: string; detail: string }

export function overviewHeroCallout(tone: OverviewTone, blockedEvents = 0): HeroCallout {
  if (tone === "healthy") {
    if (blockedEvents > 0) {
      return {
        title: blockedEvents === 1 ? "An event needs a look" : "Some events need a look",
        detail: "Review Activity for details.",
      }
    }
    return { title: "All good!", detail: "Your calendars are in sync." }
  }
  if (tone === "attention") {
    return { title: "Needs attention", detail: "Review the affected rule to continue." }
  }
  return { title: "Ready when you are", detail: "Preview comes before anything is written." }
}
