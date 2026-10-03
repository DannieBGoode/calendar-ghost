import type { OverviewTone } from "./overview-health"

export const HERO_PREVIEW_TONES: readonly OverviewTone[] = ["setup", "healthy", "attention"]

export const HERO_TONE_LABELS: Record<OverviewTone, string> = {
  setup: "Setup",
  healthy: "Healthy",
  attention: "Attention",
}

export type HeroPreviewCopy = {
  badge: string
  headline: string
  detail: string
  firstFact: string
  secondFact: string
  callout: { title: string; detail: string }
}

export function heroPreviewCopy(tone: OverviewTone): HeroPreviewCopy {
  if (tone === "healthy") {
    return {
      badge: "Healthy",
      headline: "Synchronization is healthy",
      detail: "All systems are running normally. Calendar Ghost is watching for changes and keeping your calendars in sync.",
      firstFact: "Rules running",
      secondFact: "Last sync just now",
      callout: { title: "All good!", detail: "Your calendars are in sync." },
    }
  }
  if (tone === "attention") {
    return {
      badge: "Needs attention",
      headline: "Synchronization needs attention",
      detail: "A rule needs a quick review before it can continue.",
      firstFact: "Rule needs review",
      secondFact: "Writes paused for safety",
      callout: { title: "Needs attention", detail: "Review the affected rule to continue." },
    }
  }
  return {
    badge: "Setup",
    headline: "Set up your first synchronization",
    detail: "The service is running and waiting for a Google account.",
    firstFact: "Setup in three steps",
    secondFact: "Nothing written yet",
    callout: { title: "Ready when you are", detail: "Preview comes before anything is written." },
  }
}
