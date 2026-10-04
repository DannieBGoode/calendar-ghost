import { useQuery } from "@tanstack/react-query"
import {
  ArrowRight,
  Check,
  ExternalLink,
  KeyRound,
} from "lucide-react"

import { LoadFailure } from "@/components/load-failure"
import { PageSkeleton } from "@/components/page-skeleton"
import { Button } from "@/components/ui/button"
import { GoogleReturnHelp } from "@/features/settings"
import { HealthHero } from "@/features/overview-hero"
import { OverviewRules, RecentChanges, REFRESH_INTERVAL } from "@/features/overview-sections"
import { api, type Dashboard } from "@/lib/api"
import {
  appPathForView,
  isPlainLeftClick,
  type OpenRule,
  type ViewChange,
} from "@/lib/navigation"
import { recordAuthorizationStart } from "@/lib/oauth-redirect"
import { overviewHealth } from "@/lib/overview-health"
import { workRefreshInterval } from "@/lib/rule-work"
import { useNow } from "@/lib/use-now"
import { useRuleEndpoints, type RuleEndpoints } from "@/lib/use-rule-endpoints"
import { cn } from "@/lib/utils"

function ruleName(endpoints: RuleEndpoints): string {
  return `${endpoints.source.name} → ${endpoints.destination.name}`
}

/** What the Overview reads: the dashboard, the rules and their endpoints, and Google setup. */
function useOverviewData() {
  const dashboard = useQuery({ queryKey: ["dashboard"], queryFn: api.dashboard, refetchInterval: REFRESH_INTERVAL })
  const rules = useQuery({
    queryKey: ["rules"],
    queryFn: api.rules,
    refetchInterval: (query) => workRefreshInterval(query.state.data, REFRESH_INTERVAL),
  })
  const google = useQuery({ queryKey: ["google-configuration"], queryFn: api.googleConfiguration })
  const { endpoints } = useRuleEndpoints(rules.data ?? [])
  return { dashboard, rules, google, endpoints }
}

export function OverviewView({ onViewChange, onOpenRule }: { onViewChange: ViewChange; onOpenRule: OpenRule }) {
  const now = useNow()
  const { dashboard, rules, google, endpoints } = useOverviewData()

  if (dashboard.isPending || rules.isPending || google.isPending) return <PageSkeleton label="Loading overview" />
  if (dashboard.error || rules.error || google.error) return <LoadFailure title="Calendar Ghost could not load" />

  const ruleNames = new Map(rules.data.map((rule) => [rule.id, ruleName(endpoints(rule))]))
  const health = overviewHealth(dashboard.data, now, (ruleId) => ruleNames.get(ruleId) ?? null)

  return (
    <div className="page-section overview-page">
      <HealthHero health={health} onViewChange={onViewChange} onOpenRule={onOpenRule} />

      {health.tone === "setup" && (
        <OnboardingSteps
          dashboard={dashboard.data}
          googleConfigured={google.data.configured}
          redirectUri={google.data.redirect_uri}
          onViewChange={onViewChange}
        />
      )}
      {rules.data.length > 0 && (
        <OverviewRules rules={rules.data} endpoints={endpoints} now={now} onViewChange={onViewChange} onOpenRule={onOpenRule} />
      )}
      {rules.data.some((rule) => rule.state === "enabled" || rule.last_sync) && (
        <RecentChanges rules={rules.data} endpoints={endpoints} now={now} onViewChange={onViewChange} onOpenRule={onOpenRule} />
      )}
    </div>
  )
}

function OnboardingSteps({
  dashboard,
  googleConfigured,
  redirectUri,
  onViewChange,
}: {
  dashboard: Dashboard
  googleConfigured: boolean
  redirectUri: string | null
  onViewChange: ViewChange
}) {
  // Only an authorized account lets the next step work; a disconnected one must be renewed first.
  const reauthorize = dashboard.connected_accounts === 0 && dashboard.disconnected_accounts > 0
  const done = [dashboard.connected_accounts > 0, dashboard.sync_rules > 0, dashboard.enabled_rules > 0]
  const current = done.indexOf(false)
  const rulesLink = (label: string, createRule: boolean) => (
    <Button asChild>
      <a
        href={appPathForView("rules")}
        onClick={(event) => {
          if (!isPlainLeftClick(event)) return
          event.preventDefault()
          onViewChange("rules", { createRule })
        }}
      >
        {label} <ArrowRight aria-hidden="true" />
      </a>
    </Button>
  )
  const steps = [
    reauthorize ? {
      title: "Reauthorize your Google account",
      body: "Its access was removed or expired. Renew it in Settings before creating a rule.",
      action: (
        <Button asChild>
          <a
            href={appPathForView("settings")}
            onClick={(event) => {
              if (!isPlainLeftClick(event)) return
              event.preventDefault()
              onViewChange("settings")
            }}
          >
            Reauthorize in Settings <ArrowRight aria-hidden="true" />
          </a>
        </Button>
      ),
    } : {
      title: "Connect a Google account",
      body: "Authorize calendar discovery and event access for one Google account.",
      action: (
        <div className="step-action">
          <Button disabled={!googleConfigured} onClick={() => {
              recordAuthorizationStart()
              window.location.assign("/api/v1/oauth/google/start")
            }}>
            <KeyRound aria-hidden="true" /> Connect Google account <ExternalLink aria-hidden="true" />
          </Button>
          {!googleConfigured && (
            <p className="configuration-note">
              Add the master key and Google OAuth credentials in <code>.env</code>, then restart.
            </p>
          )}
        </div>
      ),
    },
    {
      title: "Create a rule",
      body: "Choose one source calendar, one destination calendar, and what the destination may show.",
      action: rulesLink("Create a rule", true),
    },
    {
      title: "Preview and start syncing",
      body: "Review exactly what will be written before the first event reaches the destination.",
      action: rulesLink("Review rules", false),
    },
  ]
  return (
    <section className="workflow dashboard-card setup-card" aria-labelledby="workflow-title">
      <div className="section-heading">
        <div>
          <h2 id="workflow-title">Getting started</h2>
          <p>Nothing is written to Google until a rule passes preview and you start it.</p>
        </div>
        <span className="step-progress">Step {current + 1} of 3</span>
      </div>
      {current === 0 && <GoogleReturnHelp redirectUri={redirectUri} />}
      <ol className="step-list">
        {steps.map((step, index) => (
          <li
            key={step.title}
            className={cn("step-row", done[index] ? "done" : index === current ? "current" : "pending")}
            aria-current={index === current ? "step" : undefined}
          >
            <span className="step-number">
              {done[index] && <span className="sr-only">Done: </span>}
              {done[index] ? <Check aria-hidden="true" /> : index + 1}
            </span>
            <div className="step-content">
              <div><h3>{step.title}</h3><p>{step.body}</p></div>
              {index === current && step.action}
            </div>
          </li>
        ))}
      </ol>
    </section>
  )
}
