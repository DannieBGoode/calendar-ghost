import { useQuery } from "@tanstack/react-query"

import { PlanChips } from "@/components/plan-chips"
import { PlanUsage } from "@/components/plan-usage"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/i18n/provider"
import { api, type OwnPlan } from "@/lib/api"
import { connectionsPath, isPlainLeftClick } from "@/lib/navigation"
import { ownPlanCard } from "@/lib/plan-usage"
import { ownPlanShown } from "@/lib/plans"
import { useOwnPlan } from "@/lib/use-own-plan"

/** Where links beside each limit land: `yourPlanPath()` names this anchor. */
const ANCHOR = "your-plan"
const TITLE = "your-plan-title"

/**
 * Brings Your plan into view and moves focus to its heading when the address names it, as "See
 * your plan" does, so keyboard and screen reader users start there. The section appears only once
 * its data loads, after the browser looked for the anchor, so it does this itself; a stable
 * callback runs once per mount.
 */
function revealOnArrival(section: HTMLElement | null) {
  if (!section || window.location.hash !== `#${ANCHOR}`) return
  section.scrollIntoView({ block: "start" })
  section.querySelector<HTMLElement>(`#${TITLE}`)?.focus({ preventScroll: true })
}

/**
 * Which Plan limits the signed-in User, then one row per limit with a meter and how much of it they
 * use, and how to change it. An administrator reads that no plan limits them. Hidden while Plans
 * are off and for an administrator under Only Me, where Plans have no effect. A failed load shows
 * its own error; an administrator sees it only once the Registration Policy loads and is not Only
 * Me. The server still checks every limit.
 */
export function OwnPlanSection({ administrator, onOpenConnections }: { administrator: boolean; onOpenConnections: () => void }) {
  const { t } = useI18n()
  const { shown, failed, plan, retry } = useShownOwnPlan(administrator)
  if (!shown) return null
  return (
    <section ref={revealOnArrival} id={ANCHOR} className="settings-section" aria-labelledby={TITLE}>
      <div className="section-heading">
        <div>
          <h2 id={TITLE} tabIndex={-1}>
            {t("settings.ownPlan.title")}
          </h2>
          {plan && <OwnPlanIntro plan={plan} />}
        </div>
      </div>
      {plan && <OwnPlanCard plan={plan} onOpenConnections={onOpenConnections} />}
      {failed && (
        <div className="inline-error integration-load-error" role="alert">
          <span>{t("settings.ownPlan.loadError")}</span>
          <Button type="button" variant="outline" onClick={retry}>
            {t("common.loadFailure.retry")}
          </Button>
        </div>
      )}
    </section>
  )
}

/**
 * The User's Plan as Your plan shows it: whether the section shows, whether its read failed for
 * someone it limits, and the Plan once read. Only administrators may read the Registration
 * Policy, and under Only Me the only User administers, so a failed read stays hidden from them.
 */
function useShownOwnPlan(administrator: boolean) {
  const ownPlan = useOwnPlan()
  const registration = useQuery({ queryKey: ["registration"], queryFn: api.registration, enabled: administrator })
  const policy = registration.data?.policy
  const failed = ownPlan.isError && (!administrator || (policy !== undefined && policy !== "only_me"))
  return {
    shown: failed || ownPlanShown(ownPlan.data, policy),
    failed,
    plan: failed ? undefined : ownPlan.data,
    retry: () => void ownPlan.refetch(),
  }
}

/** What Your plan shows, or why no plan limits an administrator. */
function OwnPlanIntro({ plan }: { plan: OwnPlan }) {
  const { t } = useI18n()
  return <p>{t(plan.basis === "plan" && plan.plan ? "settings.ownPlan.intro" : "settings.ownPlan.administrator")}</p>
}

/**
 * The Plan as a card: its name with an "Over a limit" chip past any limit, whether it is the
 * default or the User's administrator set it, one row per limit, then the one way to change it:
 * the administrator chooses, named by role and never by person.
 */
function OwnPlanCard({ plan, onOpenConnections }: { plan: OwnPlan; onOpenConnections: () => void }) {
  const i18n = useI18n()
  const card = ownPlanCard(i18n, plan)
  if (!card) return null
  return (
    <div className="page-card own-plan-card">
      <div className="own-plan-head">
        <div className="own-plan-held">
          <h3 className="own-plan-name">{card.name}</h3>
          <PlanChips chips={card.chips} />
        </div>
        <p className="own-plan-origin">{card.origin}</p>
      </div>
      <PlanUsage
        rows={card.rows}
        noteLink={(text) => (
          <a
            href={connectionsPath()}
            onClick={(event) => {
              if (!isPlainLeftClick(event)) return
              event.preventDefault()
              onOpenConnections()
            }}
          >
            {text}
          </a>
        )}
      />
      <p className="own-plan-close">{i18n.t("settings.ownPlan.close")}</p>
    </div>
  )
}
