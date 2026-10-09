import { ArrowRight, CheckCircle2 } from "lucide-react"

import { GhostMark, type GhostExpression } from "@/components/ghost-mark"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/i18n/provider"
import {
  appPathForLocation,
  appPathForRule,
  isPlainLeftClick,
  type OpenRule,
  type ViewChange,
  type ViewOptions,
} from "@/lib/navigation"
import type { HealthAction, OverviewHealth, OverviewTone } from "@/lib/overview-health"
import { overviewHeroCallouts } from "@/lib/overview-hero"

const GHOST_EXPRESSIONS: Record<OverviewTone, GhostExpression> = {
  healthy: "happy",
  review: "concerned",
  stopped: "crying",
  waiting: "neutral",
  paused: "sleepy",
  setup: "neutral",
}
// Where successive calls for help appear around the ghost, so they read as calling out.
const CALLOUT_POSITIONS = ["beside", "above", "below", "above-left"] as const

function healthActionPath(action: HealthAction): string {
  if (action.ruleId) return appPathForRule(action.ruleId)
  const tab = action.settingsTab ? { settingsTab: action.settingsTab } : {}
  return `${appPathForLocation({ view: action.view, ruleId: null, ...tab })}${action.search ?? ""}`
}

/** Where an action leads besides its view: a filter, or the Settings tab it is about. */
function healthActionOptions({ search, settingsTab }: HealthAction): ViewOptions | undefined {
  if (!search && !settingsTab) return undefined
  return { ...(search ? { search } : {}), ...(settingsTab ? { settingsTab } : {}) }
}

/** The Overview's headline: how synchronization is doing, what to do next, and the ghost's mood. */
export function HealthHero({
  health,
  onViewChange,
  onOpenRule,
}: {
  health: OverviewHealth
  onViewChange: ViewChange
  onOpenRule: OpenRule
}) {
  const i18n = useI18n()
  const { t } = i18n
  const callouts = overviewHeroCallouts(i18n, health.tone)
  const followAction = (action: HealthAction) => (event: React.MouseEvent) => {
    if (!isPlainLeftClick(event)) return
    event.preventDefault()
    if (action.ruleId) onOpenRule(action.ruleId)
    else onViewChange(action.view, healthActionOptions(action))
  }

  return (
    <section className="health-hero" data-tone={health.tone} aria-labelledby="health-title">
      <div className="health-hero-copy">
        <h1 id="health-title">{health.headline}</h1>
        {health.title && <p className="health-hero-context">{health.title}</p>}
        <p className="health-hero-detail">{health.detail}</p>
        {health.facts.length > 0 && (
          <ul className="health-hero-facts" aria-label={t("overview.hero.factsLabel")}>
            {health.facts.map((fact, index) => (
              <li key={fact}>
                {index === 0 && health.tone === "healthy" && <CheckCircle2 aria-hidden="true" />}
                {fact}
              </li>
            ))}
          </ul>
        )}
        {health.action && health.tone !== "setup" && (
          <Button className="health-hero-action" asChild>
            <a href={healthActionPath(health.action)} onClick={followAction(health.action)}>
              {health.action.label} <ArrowRight aria-hidden="true" />
            </a>
          </Button>
        )}
        {health.others.length > 0 && (
          <div className="health-hero-others">
            <h2>{t("overview.hero.also")}</h2>
            <ul>
              {health.others.map((other) => (
                <li key={other.summary} data-tone={other.tone}>
                  <span>{other.summary}</span>
                  {other.action && (
                    <a className="text-link" href={healthActionPath(other.action)} onClick={followAction(other.action)}>
                      {other.action.label} <ArrowRight aria-hidden="true" />
                    </a>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
      <div className="health-hero-visual" aria-hidden="true">
        <div className="health-hero-character">
          <div className="health-hero-halo" />
          <div className="health-hero-sparks">
            <span className="health-hero-spark health-hero-spark-ray health-hero-spark-ray-one" />
            <span className="health-hero-spark health-hero-spark-ray health-hero-spark-ray-two" />
            <span className="health-hero-spark health-hero-spark-ray health-hero-spark-ray-three" />
            <span className="health-hero-spark health-hero-spark-dot health-hero-spark-dot-one" />
            <span className="health-hero-spark health-hero-spark-dot health-hero-spark-dot-two" />
            <span className="health-hero-spark health-hero-spark-dot health-hero-spark-dot-three" />
            <span className="health-hero-spark health-hero-spark-dot health-hero-spark-dot-four" />
          </div>
          <GhostMark className="health-hero-ghost" expression={GHOST_EXPRESSIONS[health.tone]} />
          <div className="health-hero-callouts" data-calling={callouts.length > 1 ? "" : undefined}>
            {callouts.map((callout, index) => (
              <div
                key={callout.title}
                className="health-hero-callout"
                data-position={CALLOUT_POSITIONS[index % CALLOUT_POSITIONS.length]}
                style={{ "--call-index": index, "--call-count": callouts.length } as React.CSSProperties}
              >
                <strong>{callout.title}</strong>
                {callout.detail && <span>{callout.detail}</span>}
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}
