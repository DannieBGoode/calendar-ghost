import { useQuery } from "@tanstack/react-query"

import { Button } from "@/components/ui/button"
import { useI18n } from "@/i18n/provider"
import { api, type OwnPlan } from "@/lib/api"
import { ownPlanShown, ownPlanSummary } from "@/lib/plans"
import { useOwnPlan } from "@/lib/use-own-plan"

/** Where links beside each limit land: `yourPlanPath()` names this anchor. */
const ANCHOR = "your-plan"

/**
 * Brings Your plan into view when the address names it. The section appears only once its data
 * loads, after the browser looked for the anchor, so it scrolls itself; a stable callback runs
 * once per mount.
 */
function revealOnArrival(section: HTMLElement | null) {
  if (section && window.location.hash === `#${ANCHOR}`) section.scrollIntoView({ block: "start" })
}

/**
 * What the signed-in User's Plan allows and how much of it they use, in one line, and a note when
 * more rules count than it allows. An administrator reads that no plan limits them. Hidden while
 * Plans are off and for an administrator under Only Me, where Plans have no effect. A failed load
 * shows its own error; an administrator sees it only once the Registration Policy loads and is not
 * Only Me. The server still checks every limit.
 */
export function OwnPlanSection({ administrator }: { administrator: boolean }) {
  const { t } = useI18n()
  const ownPlan = useOwnPlan()
  // Only administrators may read the Registration Policy; under Only Me the only User administers.
  const registration = useQuery({ queryKey: ["registration"], queryFn: api.registration, enabled: administrator })
  const policy = registration.data?.policy
  const failed = ownPlan.isError && (!administrator || (policy !== undefined && policy !== "only_me"))
  if (!failed && !ownPlanShown(ownPlan.data, policy)) return null
  return (
    <section ref={revealOnArrival} id={ANCHOR} className="settings-section" aria-labelledby="your-plan-title">
      <div className="section-heading">
        <div>
          <h2 id="your-plan-title">{t("settings.ownPlan.title")}</h2>
          {!failed && ownPlan.data && <OwnPlanLines plan={ownPlan.data} />}
        </div>
      </div>
      {failed && (
        <div className="inline-error integration-load-error" role="alert">
          <span>{t("settings.ownPlan.loadError")}</span>
          <Button type="button" variant="outline" onClick={() => void ownPlan.refetch()}>
            {t("common.loadFailure.retry")}
          </Button>
        </div>
      )}
    </section>
  )
}

/** The Plan in one line, or why no plan limits an administrator; then whether more rules count than it allows. */
function OwnPlanLines({ plan }: { plan: OwnPlan }) {
  const i18n = useI18n()
  const { t } = i18n
  if (plan.basis !== "plan") return <p>{t("settings.ownPlan.administrator")}</p>
  return (
    <>
      <p>{ownPlanSummary(i18n, plan)}</p>
      {plan.over_rule_limit && (
        <p className="field-hint" data-tone="attention">
          {t("settings.ownPlan.overRules", { count: plan.limits?.rules ?? 0 })}
        </p>
      )}
    </>
  )
}
