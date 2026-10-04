import type { I18n } from "@/i18n/translator"
import type { MessageKey } from "@/i18n/types"

import type { OverviewTone } from "./overview-health"

/** What the ghost says. It reacts to the state in a few words; the hero copy carries the facts. */
export type HeroCallout = { title: string; detail?: string }

type CalloutKeys = { title: MessageKey; detail?: MessageKey }

/**
 * The ghost's lines for each state. A stopped ghost calls out for help, one line at a time around
 * it; reduced motion keeps the first line still.
 */
const CALLOUTS: Record<OverviewTone, readonly CalloutKeys[]> = {
  healthy: [{ title: "overview.hero.callouts.healthy.title", detail: "overview.hero.callouts.healthy.detail" }],
  review: [{ title: "overview.hero.callouts.review.title" }],
  stopped: [
    { title: "overview.hero.callouts.stopped.help" },
    { title: "overview.hero.callouts.stopped.hand" },
    { title: "overview.hero.callouts.stopped.anyone" },
    { title: "overview.hero.callouts.stopped.over" },
  ],
  waiting: [{ title: "overview.hero.callouts.waiting.title" }],
  paused: [{ title: "overview.hero.callouts.paused.title" }],
  setup: [{ title: "overview.hero.callouts.setup.title" }],
}

export function overviewHeroCallouts(i18n: I18n, tone: OverviewTone): readonly HeroCallout[] {
  return CALLOUTS[tone].map((callout) => ({
    title: i18n.t(callout.title),
    ...(callout.detail ? { detail: i18n.t(callout.detail) } : {}),
  }))
}
