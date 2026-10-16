import { useQuery } from "@tanstack/react-query"
import { TriangleAlert } from "lucide-react"

import { Button } from "@/components/ui/button"
import { useI18n } from "@/i18n/provider"
import { api, type OwnPlan } from "@/lib/api"
import { ownPlanRows, ownPlanShown, type OwnPlanRow } from "@/lib/plans"
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
 * Which Plan limits the signed-in User, then one row per limit with how much of it they use, and
 * how to change it. An administrator reads that no plan limits them. Hidden while Plans are off
 * and for an administrator under Only Me, where Plans have no effect. A failed load shows its own
 * error; an administrator sees it only once the Registration Policy loads and is not Only Me. The
 * server still checks every limit.
 */
export function OwnPlanSection({ administrator }: { administrator: boolean }) {
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
      {plan && <OwnPlanLimits plan={plan} />}
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

/** Which Plan limits the User, or why no plan limits an administrator. */
function OwnPlanIntro({ plan }: { plan: OwnPlan }) {
  const { t } = useI18n()
  if (plan.basis !== "plan" || !plan.plan) return <p>{t("settings.ownPlan.administrator")}</p>
  return <p>{t("settings.ownPlan.intro", { name: plan.plan.name })}</p>
}

/** One row per limit, then the one way to change them: the User's administrator chooses their Plan. */
function OwnPlanLimits({ plan }: { plan: OwnPlan }) {
  const i18n = useI18n()
  const rows = ownPlanRows(i18n, plan)
  if (rows.length === 0) return null
  return (
    <div className="settings-list own-plan-list">
      {rows.map((row) => (
        <OwnPlanLimit key={row.limit} row={row} />
      ))}
      <p className="own-plan-close">{i18n.t("settings.ownPlan.close")}</p>
    </div>
  )
}

/**
 * A limit and how much of it is in use. Past it, the count takes Attention Ochre and a sentence
 * with an icon says what keeps working and how to make room, so color is never the only sign.
 */
function OwnPlanLimit({ row }: { row: OwnPlanRow }) {
  return (
    <div className="setting-row own-plan-row" id={`${ANCHOR}-${row.limit}`}>
      <div className="setting-copy">
        <h3>{row.title}</h3>
        <p className="setting-state" data-tone={row.over ? "attention" : undefined}>
          {row.value}
        </p>
        {row.hint && <p>{row.hint}</p>}
        {row.over && (
          <p className="field-hint" data-tone="attention">
            <TriangleAlert aria-hidden="true" />
            {row.over}
          </p>
        )}
      </div>
    </div>
  )
}
