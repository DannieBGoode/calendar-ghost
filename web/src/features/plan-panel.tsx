import { UserPlus, X } from "lucide-react"
import { useEffect, useRef, type KeyboardEvent } from "react"

import { PageTabs } from "@/components/page-tabs"
import { Button } from "@/components/ui/button"
import { useToast } from "@/components/ui/toast-context"
import { PlanAssign } from "@/features/plan-assign"
import { PlanEditor } from "@/features/plan-editor"
import { PlanHolders } from "@/features/plan-holders"
import type { ShowPeople } from "@/features/people-plans-status"
import { useI18n } from "@/i18n/provider"
import type { PlanAssignments, PlanSummary, PlansOverview, SyncInterval } from "@/lib/api"
import { appPathForPlanPanel, type OpenPerson, type PlanPanel as Panel, type PlanPanelTab } from "@/lib/navigation"
import { assignedResult, restoredResult, undoMoves } from "@/lib/plan-assignment"
import { copyDraft } from "@/lib/plan-draft"
import { planPanelMeta } from "@/lib/plan-panel"
import type { PlanWorkControls } from "@/lib/use-plan-work"
import type { PlanCommands } from "@/lib/use-plans"

type PanelProps = {
  overview: PlansOverview
  commands: PlanCommands
  work: PlanWorkControls
  /** The reader, whom Assign people marks "You". */
  currentUserId: string
  onShowPeople: ShowPeople
  onOpenPerson: OpenPerson
}

/**
 * The side panel beside the Plans catalog, at its own address and never a modal, as Activity's
 * entry panel is: "Plan", Close, the Plan's name as its title with who has it and what it allows,
 * then its Limits and People tabs. New plan has the editor alone. Opening it from the page moves
 * focus to its title; Escape anywhere in it, Close, and each tab's Cancel close it.
 */
export function PlanPanel({ panel, ...props }: PanelProps & { panel: Panel }) {
  const { t } = useI18n()
  const { overview, work } = props
  const plan = panel.plan === null ? null : overview.plans.find((item) => item.key === panel.plan)

  function escape(event: KeyboardEvent<HTMLElement>) {
    // A control inside that closes something of its own on Escape, such as a search, comes first.
    if (event.key !== "Escape" || event.nativeEvent.defaultPrevented) return
    event.preventDefault()
    work.closePanel()
  }

  return (
    <aside id="plan-panel" className="plan-panel" aria-labelledby="plan-panel-title" onKeyDown={escape}>
      <div className="plan-panel-bar">
        <span className="plan-panel-label">{t("people.plans.panel.label")}</span>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label={t("people.plans.panel.close")}
          aria-disabled={work.busy || undefined}
          onClick={work.closePanel}
        >
          <X aria-hidden="true" />
        </Button>
      </div>
      {plan === null && <NewPlanPanel {...props} />}
      {plan === undefined && <MissingPlan work={work} />}
      {plan && <PlanTabsPanel plan={plan} tab={panel.tab} {...props} />}
    </aside>
  )
}

/** A Plan's head, its Limits and People tabs, and the tab open, each reset as another Plan opens. */
function PlanTabsPanel({ plan, tab, ...props }: PanelProps & { plan: PlanSummary; tab: PlanPanelTab }) {
  const i18n = useI18n()
  return (
    <>
      <PanelHead title={plan.name} meta={planPanelMeta(i18n, plan)} work={props.work} />
      <PanelTabs plan={plan} tab={tab} work={props.work} />
      {tab === "limits" ? <EditPlanForm key={plan.key} plan={plan} {...props} /> : <PlanPeople key={plan.key} plan={plan} {...props} />}
    </>
  )
}

/** New plan, titled so, saying which Plan's limits it starts with when it is a copy. */
function NewPlanPanel(props: PanelProps) {
  const { t } = useI18n()
  const copied = props.overview.plans.find((item) => item.key === props.work.copyOf)
  return (
    <>
      <PanelHead
        title={t("people.plans.new")}
        meta={copied ? t("people.plans.panel.copyOf", { name: copied.name }) : null}
        work={props.work}
      />
      <NewPlanForm copied={copied} {...props} />
    </>
  )
}

/** An address naming a Plan that is not here, as one removed since. */
function MissingPlan({ work }: { work: PlanWorkControls }) {
  const { t } = useI18n()
  return (
    <>
      <PanelHead title={t("people.plans.panel.missingTitle")} meta={null} work={work} />
      <div className="plan-panel-body">
        <p role="status">{t("people.plans.panel.missing")}</p>
      </div>
    </>
  )
}

/**
 * The title, which takes focus as the panel opens from the page, and one line under it. Taking
 * focus brings it into view when it is not, as when the panel takes the catalog's place on a
 * narrow screen scrolled down to a Plan's row.
 */
function PanelHead({ title, meta, work }: { title: string; meta: string | null; work: PlanWorkControls }) {
  const heading = useRef<HTMLHeadingElement>(null)
  const { titleFocus, titleFocused } = work
  useEffect(() => {
    if (!titleFocus) return
    heading.current?.focus({ preventScroll: true })
    heading.current?.scrollIntoView({ block: "nearest" })
    titleFocused()
  }, [titleFocus, titleFocused])
  return (
    <div className="plan-panel-head">
      <h3 id="plan-panel-title" ref={heading} tabIndex={-1}>
        {title}
      </h3>
      {meta && <p className="plan-panel-meta">{meta}</p>}
    </div>
  )
}

/** Limits and People, each at its own address; People counts who has the Plan. */
function PanelTabs({ plan, tab, work }: { plan: PlanSummary; tab: PlanPanelTab; work: PlanWorkControls }) {
  const { t } = useI18n()
  const at = (next: PlanPanelTab) => appPathForPlanPanel({ plan: plan.key, tab: next })
  return (
    <PageTabs
      className="plan-panel-tabs"
      label={plan.name}
      current={tab}
      waiting={work.busy}
      onOpen={work.openTab}
      tabs={[
        { id: "limits", label: t("people.plans.panel.tabs.limits"), href: at("limits") },
        {
          id: "people",
          label: t("people.plans.panel.tabs.people"),
          href: at("people"),
          count: plan.people,
          countLabel: t("people.plans.panel.tabs.peopleCount", { count: plan.people }),
        },
      ]}
    />
  )
}

/** The offered intervals, plus a Plan's own when a later release saved one not offered here. */
function offeredWith(offered: SyncInterval[], own: SyncInterval): SyncInterval[] {
  return offered.includes(own) ? offered : [...offered, own]
}

/**
 * A Plan's Limits: its editor, which closes once saved, back on the Plan's row, saying so in a
 * toast. Save with nothing changed only closes it.
 */
function EditPlanForm({ plan, overview, commands, work }: PanelProps & { plan: PlanSummary }) {
  const i18n = useI18n()
  const toasts = useToast()
  const { change } = commands
  return (
    <PlanEditor
      plan={plan}
      enabled={overview.enabled}
      others={overview.plans.filter((other) => other.key !== plan.key).map((other) => other.name)}
      intervals={offeredWith(overview.sync_intervals, plan.limits.sync_interval)}
      pending={change.isPending}
      error={change.error}
      onSave={(payload) =>
        change.mutate(
          { key: plan.key, payload },
          {
            onSuccess: (saved) =>
              work.closeSaved(plan.key, () =>
                toasts.show({ message: i18n.t("people.plans.results.changed", { name: saved.name }) }),
              ),
          },
        )
      }
      onCancel={work.closePanel}
    />
  )
}

/**
 * New plan's editor: empty with no limits, or, from Duplicate, with another Plan's limits and a
 * name of its own, checked like any name. Once added, the panel closes, back on the new Plan's
 * row, and a toast says so with Assign people, which opens the Plan's People tab.
 */
function NewPlanForm({ copied, overview, commands, work }: PanelProps & { copied: PlanSummary | undefined }) {
  const { t } = useI18n()
  const toasts = useToast()
  const { define } = commands
  const start = copied && copyDraft(copied, t("people.plans.copyName", { name: copied.name }), overview.sync_intervals)
  return (
    <PlanEditor
      key={copied?.key ?? ""}
      plan={null}
      start={start}
      enabled={overview.enabled}
      others={overview.plans.map((plan) => plan.name)}
      intervals={overview.sync_intervals}
      pending={define.isPending}
      error={define.error}
      onSave={(payload) =>
        define.mutate(payload, {
          onSuccess: (plan) =>
            work.closeSaved(plan.key, () =>
              toasts.show({
                message: t("people.plans.results.defined", { name: plan.name }),
                action: {
                  label: t("people.plans.results.assign"),
                  icon: <UserPlus aria-hidden="true" />,
                  onSelect: () => work.openLater({ plan: plan.key, tab: "people" }),
                },
              }),
            ),
        })
      }
      onCancel={work.closePanel}
    />
  )
}

/**
 * A Plan's People: Assign people, then who has it now. Each result is a toast with Undo, which
 * gives each person back the Plan they had and says so.
 */
function PlanPeople({ plan, overview, commands, work, currentUserId, onShowPeople, onOpenPerson }: PanelProps & { plan: PlanSummary }) {
  const i18n = useI18n()
  const toasts = useToast()
  const { assign } = commands
  const given = (answer: PlanAssignments, message: string) =>
    toasts.show({
      message,
      action: {
        label: i18n.t("common.toast.undo"),
        onSelect: () =>
          assign.mutate(
            { from: plan.key, via: "undo", moves: undoMoves(answer) },
            { onSuccess: () => toasts.show({ message: restoredResult(i18n, answer) }) },
          ),
      },
    })
  return (
    <PlanAssign
      plan={plan}
      enabled={overview.enabled}
      currentUserId={currentUserId}
      assign={assign}
      onGiven={(answer) => given(answer, assignedResult(i18n, answer, plan.name))}
      onCancel={work.closePanel}
    >
      <PlanHolders
        plan={plan}
        overview={overview}
        assign={assign}
        onChanged={given}
        onOpenPerson={onOpenPerson}
        onShowPeople={onShowPeople}
      />
    </PlanAssign>
  )
}
