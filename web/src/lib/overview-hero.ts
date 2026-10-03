import type { OverviewTone } from "./overview-health"

export type HeroCallout = { title: string; detail: string }

export function overviewHeroCallout(tone: OverviewTone): HeroCallout {
  if (tone === "healthy") {
    return { title: "All good!", detail: "Your calendars are in sync." }
  }
  if (tone === "attention") {
    return { title: "Needs attention", detail: "Review the affected rule to continue." }
  }
  return { title: "Ready when you are", detail: "Preview comes before anything is written." }
}
