import { AlertCircle, Plus, RefreshCw } from "lucide-react"
import { useEffect, useRef, type ReactNode } from "react"
import { createPortal } from "react-dom"

import { GhostMark } from "@/components/ghost-mark"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { useToast } from "@/components/ui/toast-context"
import { PlansStatus, type ShowPeople } from "@/features/people-plans-status"
import { PlansCatalog } from "@/features/people-plans-table"
import { PlanEditor } from "@/features/plan-editor"
import { useSettingChange } from "@/features/use-setting-change"
import { useI18n } from "@/i18n/provider"
import type { PlansOverview } from "@/lib/api"
import { copyDraft } from "@/lib/plan-draft"
import { usePlanWork, type PlanWorkControls } from "@/lib/use-plan-work"
import { usePlans, type PlanCommands } from "@/lib/use-plans"

/**
 * People's Plans tab: the status card with the one switch first, then the catalog of Plans, or,
 * with no Plan yet, one empty state whose one action is New plan. Once a Plan exists, New plan
 * sits beside the page title, in `headingAction`. It shows only while People does, so never under
 * Only me, where the only person administers and no Plan limits an administrator. Plans are read
 * only once it opens. `onShowPeople` opens Everyone at the people a link names.
 */
export function PlansSection({
  currentUserId,
  headingAction,
  onShowPeople,
}: {
  /** The reader, whom Assign people marks "You". */
  currentUserId: string
  headingAction: HTMLElement | null
  onShowPeople: ShowPeople
}) {
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
      {plans.data && (
        <PlansContent
          overview={plans.data}
          commands={commands}
          currentUserId={currentUserId}
          headingAction={headingAction}
          onShowPeople={onShowPeople}
        />
      )}
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
 * The tab once Plans are read: the status card, then the catalog with the new Plan's form above
 * it while open, or the empty state holding that form. New plan moves beside the page title once a
 * Plan exists, outline while its form is open, so the form's Save is the one primary action.
 */
function PlansContent({
  overview,
  commands,
  currentUserId,
  headingAction,
  onShowPeople,
}: {
  overview: PlansOverview
  commands: PlanCommands
  currentUserId: string
  headingAction: HTMLElement | null
  onShowPeople: ShowPeople
}) {
  const work = usePlanWork(commands)
  const onChange = useSettingChange(commands.setting)
  const empty = overview.plans.length === 0
  const opened = work.work?.action === "new" ? work.work : null
  const newPlan = <NewPlanButton open={opened !== null} outline={!empty && opened !== null} work={work} />
  const editor = opened && <NewPlanEditor overview={overview} commands={commands} work={work} copyOf={opened.copyOf} />
  return (
    <>
      {headingAction && !empty && createPortal(newPlan, headingAction)}
      <PlansStatus overview={overview} commands={commands} onChange={onChange} onShowPeople={onShowPeople} />
      {empty ? (
        <NoPlans action={newPlan} editor={editor} />
      ) : (
        <>
          {editor && <NewPlanCard editor={editor} />}
          <PlansCatalog
            overview={overview}
            commands={commands}
            work={work}
            onChange={onChange}
            onShowPeople={onShowPeople}
            currentUserId={currentUserId}
          />
        </>
      )}
    </>
  )
}

/**
 * New plan: it opens the new Plan's form, waits while a Plan command is on its way, and takes
 * focus where it shows when asked, as after a removal or the form's Cancel.
 */
function NewPlanButton({ open, outline, work }: { open: boolean; outline: boolean; work: PlanWorkControls }) {
  const { t } = useI18n()
  const button = useRef<HTMLButtonElement>(null)
  const { newFocus, newFocused } = work
  useEffect(() => {
    if (!newFocus) return
    button.current?.focus()
    newFocused()
  }, [newFocus, newFocused])
  return (
    <Button
      ref={button}
      id="plans-new"
      type="button"
      variant={outline ? "outline" : "default"}
      aria-expanded={open}
      aria-controls={open ? "plan-edit-new" : undefined}
      aria-disabled={work.busy || undefined}
      onClick={() => work.open({ action: "new", copyOf: null })}
    >
      <Plus aria-hidden="true" />
      {t("people.plans.new")}
    </Button>
  )
}

/** The new Plan's form above the catalog, titled New plan. */
function NewPlanCard({ editor }: { editor: ReactNode }) {
  const { t } = useI18n()
  return (
    <section id="plan-new" className="page-card plan-new-card" aria-labelledby="plan-new-title">
      <h3 id="plan-new-title">{t("people.plans.new")}</h3>
      {editor}
    </section>
  )
}

/** With no Plan yet, what Plans are for, and New plan, the tab's one action, with its form under it. */
function NoPlans({ action, editor }: { action: ReactNode; editor: ReactNode }) {
  const { t } = useI18n()
  return (
    <section id="plans-empty" className="page-card plans-empty-card" aria-labelledby="plans-empty-title">
      <div className="plans-empty">
        <GhostMark className="empty-ghost" />
        <h3 id="plans-empty-title">{t("people.plans.empty.title")}</h3>
        <p>{t("people.plans.empty.body")}</p>
        <div className="plans-empty-action">{action}</div>
      </div>
      {editor}
    </section>
  )
}

/**
 * The form that adds a Plan: empty with no limits, or, from Duplicate, with another Plan's limits
 * and a name of its own, checked like any name. Once added, the Plan's row takes focus.
 */
function NewPlanEditor({
  overview,
  commands,
  work,
  copyOf,
}: {
  overview: PlansOverview
  commands: PlanCommands
  work: PlanWorkControls
  copyOf: string | null
}) {
  const { t } = useI18n()
  const toasts = useToast()
  const { define } = commands
  const copied = overview.plans.find((plan) => plan.key === copyOf)
  const start = copied && copyDraft(copied, t("people.plans.copyName", { name: copied.name }), overview.sync_intervals)
  return (
    <div id="plan-edit-new" className="plan-new-editor">
      <PlanEditor
        key={copyOf ?? ""}
        plan={null}
        start={start}
        enabled={overview.enabled}
        others={overview.plans.map((plan) => plan.name)}
        intervals={overview.sync_intervals}
        pending={define.isPending}
        error={define.error}
        onSave={(payload) =>
          define.mutate(payload, {
            onSuccess: (plan) => {
              toasts.show({ message: t("people.plans.results.defined", { name: plan.name }) })
              work.closeAdded(plan.key)
            },
          })
        }
        onCancel={work.closeToNew}
      />
    </div>
  )
}
