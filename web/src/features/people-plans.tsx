import { Plus, TriangleAlert } from "lucide-react"
import { useRef, useState, type RefObject } from "react"

import { GhostMark } from "@/components/ghost-mark"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { PlanRemoval, type ShowHolders } from "@/features/people-plan-removal"
import { PlansSetting } from "@/features/people-plans-setting"
import { PlanEditor } from "@/features/plan-editor"
import { useI18n } from "@/i18n/provider"
import type { I18n } from "@/i18n/translator"
import type { PlanSummary, PlansOverview, SyncInterval } from "@/lib/api"
import { intervalLabel, limitsNothing, planLimitsSummary } from "@/lib/plans"
import { usePlans, type PlanCommands } from "@/lib/use-plans"

/** The one form or confirmation open in the section: a Plan's edit or removal, or a new Plan. */
type Opened = { action: "edit" | "remove"; key: string } | { action: "add" } | null
type Open = (next: Opened) => void

/**
 * People's Plans tab, in the order setting up needs: each Plan with its limits, an inline edit, and
 * Remove, then Add a plan; then the Default Plan; then whether Plans limit people. With no Plan yet
 * it holds only an empty state whose one action is Add a plan. It shows only while People does, so
 * never under Only me, where the only person administers and no Plan limits an administrator;
 * Plans are read only once it opens, or once Everyone shows that a Plan exists. `onShowHolders`
 * lists who has a Plan, from the note Remove opens on a Plan someone has.
 */
export function PlansSection({ onShowHolders }: { onShowHolders: ShowHolders }) {
  const { t } = useI18n()
  const commands = usePlans()
  const { plans, message } = commands
  const overview = plans.data
  return (
    <section className="settings-section" aria-labelledby="plans-title">
      <div className="section-heading">
        <div>
          <h2 id="plans-title">{t("people.plans.title")}</h2>
          <p>{t("people.plans.intro")}</p>
        </div>
      </div>
      {plans.isPending && <Skeleton className="h-16 w-full" />}
      {plans.error && (
        <div className="inline-error integration-load-error" role="alert">
          <span>{t("people.plans.loadError")}</span>
          <Button type="button" variant="outline" onClick={() => void plans.refetch()}>
            {t("people.plans.tryAgain")}
          </Button>
        </div>
      )}
      {overview?.plans && <PlansList overview={overview} commands={commands} onShowHolders={onShowHolders} />}
      {overview?.plans && (overview.plans.length > 0 || overview.enabled) && (
        <PlansSetting overview={overview} commands={commands} />
      )}
      {/* Always present, so a screen reader announces each change as it is saved. */}
      <p role="status" className={message ? undefined : "sr-only"}>
        {message}
      </p>
    </section>
  )
}

function PlansList({
  overview,
  commands,
  onShowHolders,
}: {
  overview: PlansOverview
  commands: PlanCommands
  onShowHolders: ShowHolders
}) {
  const [opened, setOpened] = useState<Opened>(null)
  const addButton = useRef<HTMLButtonElement>(null)
  // While a Plan is saved or removed, no other form or confirmation opens: opening one forgets
  // the command on its way, and a refusal it met would show nowhere.
  const busy = commands.define.isPending || commands.change.isPending || commands.remove.isPending

  // Opening one form or confirmation closes any other, and forgets their refusals.
  function open(next: Opened) {
    commands.define.reset()
    commands.change.reset()
    commands.remove.reset()
    setOpened(next)
  }

  const empty = overview.plans.length === 0

  // Add a plan keeps its place among the children whether or not Plans exist, so focus can return
  // to it once the first Plan is added and the empty state gives way to the list.
  return (
    <div className="settings-list">
      {empty && <NoPlans />}
      {overview.plans.map((plan) => (
        <PlanItem
          key={plan.key}
          plan={plan}
          enabled={overview.enabled}
          others={otherNames(overview.plans, plan.key)}
          intervals={editorIntervals(overview.sync_intervals, plan)}
          opened={opened}
          busy={busy}
          onOpen={open}
          commands={commands}
          onShowHolders={onShowHolders}
          onRemoved={() => {
            open(null)
            addButton.current?.focus()
          }}
        />
      ))}
      <AddPlanItem
        empty={empty}
        enabled={overview.enabled}
        others={otherNames(overview.plans, null)}
        intervals={overview.sync_intervals}
        adding={opened?.action === "add"}
        busy={busy}
        onOpen={open}
        commands={commands}
        addButton={addButton}
      />
    </div>
  )
}

/** The names of every Plan but the one with `key`, which a Plan's name may not read as. */
function otherNames(plans: readonly PlanSummary[], key: string | null): string[] {
  return plans.filter((plan) => plan.key !== key).map((plan) => plan.name)
}

/** The offered intervals, plus a Plan's own when a later release saved one not offered here. */
function editorIntervals(offered: SyncInterval[], plan: PlanSummary): SyncInterval[] {
  const own = plan.limits.sync_interval
  return offered.includes(own) ? offered : [...offered, own]
}

/** With no Plan yet, what Plans are for; Add a plan, right after it, is its one action. */
function NoPlans() {
  const { t } = useI18n()
  return (
    <div className="plans-empty">
      <GhostMark className="empty-ghost" />
      <h3>{t("people.plans.empty.title")}</h3>
      <p>{t("people.plans.empty.body")}</p>
    </div>
  )
}

/**
 * Who has a Plan, and whom it limits, as two facts with one wording everywhere: everyone who has
 * it ("4 people have it."), as Remove and the person page count them, then the active people it
 * limits who do not administer ("Limits 3 people."), nobody for a Plan that limits nothing, and
 * only once Plans are on.
 */
function planReach({ t }: I18n, plan: PlanSummary, enabled: boolean): string {
  if (plan.people === 0) return t("people.plans.holdersNone")
  const holders = t("people.plans.holders", { count: plan.people })
  const count = limitsNothing(plan.limits) ? 0 : plan.limited_people
  if (count === 0) return t("people.plans.limitedNone", { holders })
  return t(enabled ? "people.plans.limited" : "people.plans.limitedLater", { holders, count })
}

/**
 * How many of the people a Plan limits have more than it allows, as after a limit was lowered, in
 * Attention Ochre with an icon, so the tone is never the only sign. Nothing while nobody does.
 */
function PlanOver({ count }: { count: number }) {
  const { t } = useI18n()
  if (count === 0) return null
  return (
    <p className="field-hint" data-tone="attention">
      <TriangleAlert aria-hidden="true" />
      {t("people.plans.over", { count })}
    </p>
  )
}

/**
 * One Plan: its name, limits, interval, who has it and whom it limits, and how many of them have
 * more than it allows, with Edit and Remove. The default has no Remove: it says how to remove it
 * instead.
 */
function PlanItem({
  plan,
  enabled,
  others,
  intervals,
  opened,
  busy,
  onOpen,
  commands,
  onShowHolders,
  onRemoved,
}: {
  plan: PlanSummary
  /** Plans limit people now. */
  enabled: boolean
  /** The names of every other Plan. */
  others: readonly string[]
  intervals: SyncInterval[]
  opened: Opened
  /** A Plan command is on its way, so Edit and Remove wait. They stay focusable: focus returns to them as its form closes. */
  busy: boolean
  onOpen: Open
  commands: PlanCommands
  onShowHolders: ShowHolders
  /** Moves focus on once the Plan's row is gone. */
  onRemoved: () => void
}) {
  const i18n = useI18n()
  const editButton = useRef<HTMLButtonElement>(null)
  const removeButton = useRef<HTMLButtonElement>(null)
  const shown = opened !== null && opened.action !== "add" && opened.key === plan.key ? opened.action : null
  const editing = shown === "edit"
  const removing = shown === "remove" && !plan.is_default
  const { change } = commands

  function close(toggle: RefObject<HTMLButtonElement | null>) {
    onOpen(null)
    toggle.current?.focus()
  }

  return (
    <div className="setting-item">
      <div className="setting-row">
        <div className="setting-copy">
          <div className="plan-title">
            <h3>{plan.name}</h3>
            {plan.is_default && <Badge variant="neutral">{i18n.t("people.plans.isDefault")}</Badge>}
          </div>
          <p>{planLimitsSummary(i18n, plan.limits)}</p>
          <p>{intervalLabel(i18n, plan.limits.sync_interval)}</p>
          <p>{planReach(i18n, plan, enabled)}</p>
          <PlanOver count={plan.over_people} />
        </div>
        <PlanActions
          plan={plan}
          editing={editing}
          removing={removing}
          busy={busy}
          onOpen={onOpen}
          editButton={editButton}
          removeButton={removeButton}
        />
      </div>
      {editing && (
        <div id={`plan-edit-${plan.key}`}>
          <PlanEditor
            plan={plan}
            enabled={enabled}
            others={others}
            intervals={intervals}
            pending={change.isPending}
            error={change.error}
            onSave={(payload) => change.mutate({ key: plan.key, payload }, { onSuccess: () => close(editButton) })}
            onCancel={() => close(editButton)}
          />
        </div>
      )}
      {removing && (
        <PlanRemoval
          plan={plan}
          commands={commands}
          onShowHolders={onShowHolders}
          onRemoved={onRemoved}
          onKeep={() => close(removeButton)}
        />
      )}
    </div>
  )
}

/**
 * A Plan's Edit, and Remove, which opens and closes what it shows. Each names the Plan, and the
 * form or note it opens only while open. The default Plan has a line on how to remove it instead.
 */
function PlanActions({
  plan,
  editing,
  removing,
  busy,
  onOpen,
  editButton,
  removeButton,
}: {
  plan: PlanSummary
  editing: boolean
  removing: boolean
  busy: boolean
  onOpen: Open
  editButton: RefObject<HTMLButtonElement | null>
  removeButton: RefObject<HTMLButtonElement | null>
}) {
  const { t } = useI18n()
  const waiting = busy || undefined
  return (
    <div className="setting-form-actions">
      <Button
        ref={editButton}
        type="button"
        variant="outline"
        aria-label={t("people.plans.editLabel", { name: plan.name })}
        aria-expanded={editing}
        aria-controls={editing ? `plan-edit-${plan.key}` : undefined}
        aria-disabled={waiting}
        onClick={() => !busy && onOpen({ action: "edit", key: plan.key })}
      >
        {t("people.plans.edit")}
      </Button>
      {plan.is_default ? (
        <p className="plan-remove-note">{t("people.plans.removeDefault")}</p>
      ) : (
        <Button
          ref={removeButton}
          type="button"
          variant="ghost"
          aria-label={t("people.plans.removeLabel", { name: plan.name })}
          aria-expanded={removing}
          aria-controls={removing ? `plan-remove-${plan.key}` : undefined}
          aria-disabled={waiting}
          onClick={() => !busy && onOpen(removing ? null : { action: "remove", key: plan.key })}
        >
          {t("people.plans.remove")}
        </Button>
      )}
    </div>
  )
}

/** "Add a plan", and its inline form once opened. With no Plan yet it closes the empty state above it. */
function AddPlanItem({
  empty,
  enabled,
  others,
  intervals,
  adding,
  busy,
  onOpen,
  commands,
  addButton,
}: {
  /** No Plan exists yet. */
  empty: boolean
  /** Plans limit people now. */
  enabled: boolean
  /** The names of every Plan. */
  others: readonly string[]
  intervals: SyncInterval[]
  adding: boolean
  /** A Plan command is on its way, so Add a plan waits. It stays focusable: focus returns to it as its form closes. */
  busy: boolean
  onOpen: Open
  commands: PlanCommands
  addButton: RefObject<HTMLButtonElement | null>
}) {
  const { t } = useI18n()
  const { define } = commands

  function close() {
    onOpen(null)
    addButton.current?.focus()
  }

  return (
    <div className="setting-item">
      <div className={empty ? "plans-empty-action" : "setting-row"}>
        <Button
          ref={addButton}
          id="plans-add"
          type="button"
          variant="outline"
          aria-expanded={adding}
          aria-controls={adding ? "plan-edit-new" : undefined}
          aria-disabled={busy || undefined}
          onClick={() => !busy && onOpen({ action: "add" })}
        >
          <Plus aria-hidden="true" />
          {t("people.plans.add")}
        </Button>
      </div>
      {adding && (
        <div id="plan-edit-new">
          <PlanEditor
            plan={null}
            enabled={enabled}
            others={others}
            intervals={intervals}
            pending={define.isPending}
            error={define.error}
            onSave={(payload) => define.mutate(payload, { onSuccess: close })}
            onCancel={close}
          />
        </div>
      )}
    </div>
  )
}
