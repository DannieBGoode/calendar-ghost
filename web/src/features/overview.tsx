import { useQuery } from "@tanstack/react-query"
import {
  ArrowRight,
  Check,
  Plus,
} from "lucide-react"

import { ConnectAccount } from "@/components/connect-account"
import { LoadFailure } from "@/components/load-failure"
import { PageSkeleton } from "@/components/page-skeleton"
import { Button } from "@/components/ui/button"
import { OAuthReturnHelp } from "@/features/settings"
import { useI18n } from "@/i18n/provider"
import { codeTag, rich } from "@/i18n/rich"
import type { I18n } from "@/i18n/translator"
import { HealthHero } from "@/features/overview-hero"
import { OverviewRules, RecentChanges, REFRESH_INTERVAL } from "@/features/overview-sections"
import { api, type CalendarProvider, type Dashboard } from "@/lib/api"
import {
  appPathForView,
  connectionsPath,
  isPlainLeftClick,
  type OpenRule,
  type ViewChange,
} from "@/lib/navigation"
import { overviewHealth } from "@/lib/overview-health"
import { isAdministrator } from "@/lib/people"
import { workRefreshInterval } from "@/lib/rule-work"
import { useNow } from "@/lib/use-now"
import { useAccountLimitReason, usePlanHoldStep } from "@/lib/use-own-plan"
import { useRuleEndpoints, type RuleEndpoints } from "@/lib/use-rule-endpoints"
import { cn } from "@/lib/utils"

function ruleName(i18n: I18n, endpoints: RuleEndpoints): string {
  return i18n.t("overview.ruleName", { source: endpoints.source.name, destination: endpoints.destination.name })
}

/**
 * What the Overview reads: the dashboard, the rules and their endpoints, the providers, and how
 * often the reader's rules are checked.
 */
function useOverviewData() {
  const dashboard = useQuery({ queryKey: ["dashboard"], queryFn: api.dashboard, refetchInterval: REFRESH_INTERVAL })
  const rules = useQuery({
    queryKey: ["rules"],
    queryFn: api.rules,
    refetchInterval: (query) => workRefreshInterval(query.state.data, REFRESH_INTERVAL),
  })
  const providers = useQuery({ queryKey: ["providers"], queryFn: api.providers })
  const session = useQuery({ queryKey: ["session"], queryFn: api.session })
  const { endpoints } = useRuleEndpoints(rules.data ?? [])
  // An administrator fixes the installation's own Causes; everyone else is told it is not theirs.
  const administrator = isAdministrator(session.data?.user)
  // Every rule of one User polls alike, and the rules answer refreshes while the Overview is open,
  // so a Plan changed meanwhile shows at the next refresh. With no rules it says the default.
  const pollEveryMinutes = rules.data?.[0]?.poll_every_minutes
  return { dashboard, rules, providers, endpoints, administrator, pollEveryMinutes }
}

export function OverviewView({ onViewChange, onOpenRule }: { onViewChange: ViewChange; onOpenRule: OpenRule }) {
  const i18n = useI18n()
  const { t } = i18n
  const now = useNow()
  const { dashboard, rules, providers, endpoints, administrator, pollEveryMinutes } = useOverviewData()
  const planHoldStep = usePlanHoldStep()

  if (dashboard.isPending || rules.isPending || providers.isPending) return <PageSkeleton label={t("overview.loading")} />
  if (dashboard.error || rules.error || providers.error) return <LoadFailure title={t("overview.loadFailure")} />

  const ruleNames = new Map(rules.data.map((rule) => [rule.id, ruleName(i18n, endpoints(rule))]))
  const health = overviewHealth(i18n, dashboard.data, now, {
    ruleName: (ruleId) => ruleNames.get(ruleId) ?? null,
    administrator,
    pollEveryMinutes,
    planHoldStep,
  })

  return (
    <div className="page-section overview-page">
      <HealthHero health={health} onViewChange={onViewChange} onOpenRule={onOpenRule} />

      {health.tone === "setup" && (
        <OnboardingSteps dashboard={dashboard.data} providers={providers.data} onViewChange={onViewChange} />
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
  providers,
  onViewChange,
}: {
  dashboard: Dashboard
  providers: CalendarProvider[]
  onViewChange: ViewChange
}) {
  const { t } = useI18n()
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
      title: t("overview.onboarding.steps.reauthorize.title"),
      body: t("overview.onboarding.steps.reauthorize.body"),
      action: (
        <Button asChild>
          <a
            href={connectionsPath()}
            onClick={(event) => {
              if (!isPlainLeftClick(event)) return
              event.preventDefault()
              onViewChange("settings", { settingsTab: "connections" })
            }}
          >
            {t("overview.health.action.reauthorizeInSettings")} <ArrowRight aria-hidden="true" />
          </a>
        </Button>
      ),
    } : {
      title: t("overview.onboarding.steps.connect.title"),
      body: t("overview.onboarding.steps.connect.body"),
      action: <ConnectStep providers={providers} />,
    },
    {
      title: t("overview.onboarding.steps.createRule.title"),
      body: t("overview.onboarding.steps.createRule.body"),
      action: rulesLink(t("overview.health.action.createRule"), true),
    },
    {
      title: t("overview.onboarding.steps.preview.title"),
      body: t("overview.onboarding.steps.preview.body"),
      action: rulesLink(t("overview.health.action.reviewRules"), false),
    },
  ]
  return (
    <section className="workflow dashboard-card setup-card" aria-labelledby="workflow-title">
      <div className="section-heading">
        <div>
          <h2 id="workflow-title">{t("overview.onboarding.title")}</h2>
          <p>{t("overview.onboarding.intro")}</p>
        </div>
        <span className="step-progress">{t("overview.onboarding.stepProgress", { current: current + 1 })}</span>
      </div>
      {current === 0 && <OAuthReturnHelp providers={providers} />}
      <ol className="step-list">
        {steps.map((step, index) => (
          <li
            key={step.title}
            className={cn("step-row", done[index] ? "done" : index === current ? "current" : "pending")}
            aria-current={index === current ? "step" : undefined}
          >
            <span className="step-number">
              {done[index] && <span className="sr-only">{t("overview.onboarding.doneSr")}</span>}
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

/** The one Connect action, or why no account can be connected yet. */
function ConnectStep({ providers }: { providers: CalendarProvider[] }) {
  const { t } = useI18n()
  // Read before the early return below, as the rules of hooks require.
  const accountLimit = useAccountLimitReason()
  if (providers.length === 0) {
    return (
      <div className="step-action">
        <Button disabled>
          <Plus aria-hidden="true" /> {t("common.connectAccount.menu")}
        </Button>
        <p className="configuration-note">
          {rich(t("overview.onboarding.steps.connect.configurationNote"), { code: codeTag })}
        </p>
      </div>
    )
  }
  return (
    <div className="step-action">
      <ConnectAccount providers={providers} primary disabledReason={accountLimit} />
    </div>
  )
}
