import { AlertCircle, Plus, RefreshCw } from "lucide-react"
import { useEffect, type ReactNode } from "react"
import { createPortal } from "react-dom"

import { GhostMark } from "@/components/ghost-mark"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { PlansStatus, type ShowPeople } from "@/features/people-plans-status"
import { PlansCatalog } from "@/features/people-plans-table"
import { PlanPanel } from "@/features/plan-panel"
import { useSettingChange } from "@/features/use-setting-change"
import { useI18n } from "@/i18n/provider"
import type { PlansOverview } from "@/lib/api"
import type { OpenPerson, OpenPlan } from "@/lib/navigation"
import { usePlanWork, type PlanWorkControls } from "@/lib/use-plan-work"
import { usePlans, type PlanCommands } from "@/lib/use-plans"

/** What the Plans tab needs from People around it. */
type PlansContext = {
  /** The reader, whom Assign people marks "You". */
  currentUserId: string
  headingAction: HTMLElement | null
  /** Opens Everyone at the people a link names. */
  onShowPeople: ShowPeople
  /** Opens one person's page, as a link to someone who has a Plan does. */
  onOpenPerson: OpenPerson
  /** Opens a Plan's panel as a new arrival, for a toast's next step once this tab is gone. */
  onOpenPlan: OpenPlan
  /** The arrival opens a Plan's panel from elsewhere, so it takes focus as from the page. */
  panelFocus: boolean
}

/**
 * People's Plans tab: the status card with the one switch first, then the catalog of Plans, or,
 * with no Plan yet, one empty state whose one action is New plan; and beside them, at its own
 * address, a Plan's side panel. Once a Plan exists, New plan sits beside the page title, in
 * `headingAction`. It shows only while People does, so never under Only me, where the only person
 * administers and no Plan limits an administrator. Plans are read only once it opens.
 */
export function PlansSection(context: PlansContext) {
  const { t } = useI18n()
  const commands = usePlans()
  const { plans } = commands
  return (
    <section className="plans-tab" aria-labelledby="plans-title">
      <h2 id="plans-title" className="sr-only">
        {t("people.plans.title")}
      </h2>
      {plans.isPending && <PlansSkeleton />}
      {!plans.data && plans.error && <PlansLoadError onRetry={() => void plans.refetch()} />}
      {plans.data && <PlansContent overview={plans.data} commands={commands} {...context} />}
    </section>
  )
}

/** Skeletons in the shape of the status card and the catalog, so nothing moves as Plans arrive. */
function PlansSkeleton() {
  const { t } = useI18n()
  return (
    <div className="plans-skeleton" aria-busy="true" aria-label={t("people.plans.loading")} role="status">
      <div className="page-card plans-skeleton-card plans-skeleton-status">
        <div className="plans-skeleton-lines">
          <Skeleton className="h-5 w-36" />
          <Skeleton className="h-3.5 w-full" />
        </div>
        <Skeleton className="h-11 w-26 rounded-full" />
      </div>
      <div className="page-card plans-skeleton-card plans-skeleton-table">
        <Skeleton className="h-3.5 w-24" />
        <Skeleton className="h-9 w-full" />
        <Skeleton className="h-9 w-full" />
        <Skeleton className="h-9 w-full" />
      </div>
    </div>
  )
}

/** Plans could not be read: nothing changed for anyone, and Try again reads them again. */
function PlansLoadError({ onRetry }: { onRetry: () => void }) {
  const { t } = useI18n()
  return (
    <div className="plans-load-error" role="alert">
      <AlertCircle aria-hidden="true" />
      <span>{t("people.plans.loadError")}</span>
      <Button type="button" variant="outline" size="sm" onClick={onRetry}>
        <RefreshCw aria-hidden="true" />
        {t("people.plans.tryAgain")}
      </Button>
    </div>
  )
}

/**
 * Once the panel closes, or a removed Plan's confirmation does, the page returns to where it was
 * before the panel opened, and focus to the Plan's name in the catalog, or to New plan, wherever it
 * shows now, as when a new Plan is not listed yet; then what follows, such as the save's toast,
 * which returns focus there as it closes.
 */
function useFocusReturn({ focusReturn, focusReturned }: PlanWorkControls) {
  useEffect(() => {
    if (focusReturn === null) return
    if (focusReturn.scrollY !== undefined) window.scrollTo({ top: focusReturn.scrollY })
    const name = focusReturn.plan === null ? null : document.getElementById(`plan-name-${focusReturn.plan}`)
    ;(name ?? document.getElementById("plans-new"))?.focus()
    focusReturn.afterwards?.()
    focusReturned()
  }, [focusReturn, focusReturned])
}

/**
 * The tab once Plans are read: the status card, then the catalog or the empty state, and, while
 * open, a Plan's side panel beside them, which then holds the one primary action, so New plan
 * turns outline. On a narrow tab the panel takes their place.
 */
function PlansContent({ overview, commands, ...context }: PlansContext & { overview: PlansOverview; commands: PlanCommands }) {
  const work = usePlanWork(commands, context.onOpenPlan, context.panelFocus)
  const onChange = useSettingChange(commands.setting)
  useFocusReturn(work)
  const empty = overview.plans.length === 0
  const { panel } = work
  const newPlan = <NewPlanButton outline={panel !== null} work={work} />
  return (
    <div className="plans-layout" data-panel={panel !== null || undefined}>
      {context.headingAction && !empty && createPortal(newPlan, context.headingAction)}
      <div className="plans-main">
        <PlansStatus
          overview={overview}
          commands={commands}
          compact={panel !== null}
          onChange={onChange}
          onShowPeople={context.onShowPeople}
        />
        {empty ? (
          <NoPlans action={newPlan} />
        ) : (
          <PlansCatalog overview={overview} commands={commands} work={work} onChange={onChange} onShowPeople={context.onShowPeople} />
        )}
      </div>
      {panel && <PlanPanel panel={panel} overview={overview} commands={commands} work={work} {...context} />}
    </div>
  )
}

/** New plan: it opens a new Plan's panel, and waits while a Plan command is on its way. */
function NewPlanButton({ outline, work }: { outline: boolean; work: PlanWorkControls }) {
  const { t } = useI18n()
  return (
    <Button
      id="plans-new"
      type="button"
      variant={outline ? "outline" : "default"}
      aria-disabled={work.busy || undefined}
      onClick={() => work.openPanel({ plan: null, tab: "limits" })}
    >
      <Plus aria-hidden="true" />
      {t("people.plans.new")}
    </Button>
  )
}

/** With no Plan yet, what Plans are for, and New plan, the tab's one action. */
function NoPlans({ action }: { action: ReactNode }) {
  const { t } = useI18n()
  return (
    <section id="plans-empty" className="page-card plans-empty-card" aria-labelledby="plans-empty-title">
      <div className="plans-empty">
        <GhostMark className="empty-ghost" />
        <h3 id="plans-empty-title">{t("people.plans.empty.title")}</h3>
        <p>{t("people.plans.empty.body")}</p>
        <div className="plans-empty-action">{action}</div>
      </div>
    </section>
  )
}
