import { Plus } from "lucide-react"
import { useRef, useState, type RefObject } from "react"

import { DestructiveConfirmation } from "@/components/destructive-confirmation"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { NativeSelect } from "@/components/ui/native-select"
import { Skeleton } from "@/components/ui/skeleton"
import { PlanEditor } from "@/features/plan-editor"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import type { PlanSummary, PlansOverview, SyncInterval } from "@/lib/api"
import { intervalLabel, planLimitsSummary } from "@/lib/plans"
import type { PlanCommands } from "@/lib/use-plans"

/** The one form or confirmation open in the section: a Plan's edit or removal, or a new Plan. */
type Opened = { action: "edit" | "remove"; key: string } | { action: "add" } | null
type Open = (next: Opened) => void

/**
 * Plans, between who can join and storage: whether Plans limit people, the Default Plan, and each
 * Plan with its limits, an inline edit, and Remove. Settings shows it only under Invitation only:
 * under Only me the only person administers, and no Plan limits an administrator.
 */
export function PlansSection({ commands }: { commands: PlanCommands }) {
  const { t } = useI18n()
  const { plans, message } = commands
  const overview = plans.data
  return (
    <section className="settings-section" aria-labelledby="plans-title">
      <div className="section-heading">
        <div>
          <h2 id="plans-title">{t("settings.plans.title")}</h2>
          <p>{t("settings.plans.intro")}</p>
        </div>
      </div>
      {plans.isPending && <Skeleton className="h-16 w-full" />}
      {plans.error && (
        <div className="inline-error integration-load-error" role="alert">
          <span>{t("settings.plans.loadError")}</span>
          <Button type="button" variant="outline" onClick={() => void plans.refetch()}>
            {t("settings.plans.tryAgain")}
          </Button>
        </div>
      )}
      {overview?.plans && <PlansList overview={overview} commands={commands} />}
      {/* Always present, so a screen reader announces each change as it is saved. */}
      <p role="status" className={message ? undefined : "sr-only"}>
        {message}
      </p>
    </section>
  )
}

function PlansList({ overview, commands }: { overview: PlansOverview; commands: PlanCommands }) {
  const [opened, setOpened] = useState<Opened>(null)
  const addButton = useRef<HTMLButtonElement>(null)

  // Opening one form or confirmation closes any other, and forgets their refusals.
  function open(next: Opened) {
    commands.define.reset()
    commands.change.reset()
    commands.remove.reset()
    setOpened(next)
  }

  return (
    <div className="settings-list">
      <EnabledItem overview={overview} commands={commands} />
      <DefaultItem overview={overview} commands={commands} />
      {overview.plans.map((plan) => (
        <PlanItem
          key={plan.key}
          plan={plan}
          intervals={editorIntervals(overview.sync_intervals, plan)}
          opened={opened}
          onOpen={open}
          commands={commands}
          onRemoved={() => {
            open(null)
            addButton.current?.focus()
          }}
        />
      ))}
      <AddPlanItem
        intervals={overview.sync_intervals}
        adding={opened?.action === "add"}
        onOpen={open}
        commands={commands}
        addButton={addButton}
      />
    </div>
  )
}

/** The offered intervals, plus a Plan's own when a later release saved one not offered here. */
function editorIntervals(offered: SyncInterval[], plan: PlanSummary): SyncInterval[] {
  const own = plan.limits.sync_interval
  return offered.includes(own) ? offered : [...offered, own]
}

/** Whether Plans limit people. It turns on only once a default exists, and keeps that default. */
function EnabledItem({ overview, commands }: { overview: PlansOverview; commands: PlanCommands }) {
  const { t } = useI18n()
  const { setting } = commands
  const hasDefault = overview.default_plan !== null
  // While a change is on its way, the box shows what was asked for.
  const checked = setting.isPending ? setting.variables.enabled : overview.enabled
  return (
    <div className="setting-item">
      <div className="setting-row">
        <label className="checkbox-row" htmlFor="plans-enabled">
          <input
            id="plans-enabled"
            type="checkbox"
            checked={checked}
            disabled={setting.isPending || (!hasDefault && !overview.enabled)}
            aria-describedby="plans-enabled-hint"
            onChange={(event) => setting.mutate({ enabled: event.target.checked, defaultPlan: overview.default_plan })}
          />
          <span>
            <strong>{t("settings.plans.enabled.label")}</strong>
            <small id="plans-enabled-hint">
              {hasDefault ? t("settings.plans.enabled.hint") : t("settings.plans.enabled.needsDefault")}
            </small>
          </span>
        </label>
      </div>
    </div>
  )
}

/** The Default Plan. It cannot be cleared while Plans limit people. */
function DefaultItem({ overview, commands }: { overview: PlansOverview; commands: PlanCommands }) {
  const i18n = useI18n()
  const { t } = i18n
  const { setting } = commands
  return (
    <div className="setting-item">
      <div className="setting-row">
        <div className="setting-copy">
          <h3 id="plans-default-title">{t("settings.plans.default.label")}</h3>
          <p id="plans-default-hint">{t("settings.plans.default.hint")}</p>
        </div>
        <div className="appearance-control">
          <NativeSelect
            id="plans-default"
            aria-labelledby="plans-default-title"
            aria-describedby="plans-default-hint"
            value={(setting.isPending ? setting.variables.defaultPlan : overview.default_plan) ?? ""}
            disabled={setting.isPending}
            onChange={(event) => setting.mutate({ enabled: overview.enabled, defaultPlan: event.target.value || null })}
          >
            <option value="" disabled={overview.enabled}>
              {t("settings.plans.default.none")}
            </option>
            {overview.plans.map((plan) => (
              <option key={plan.key} value={plan.key}>
                {plan.name}
              </option>
            ))}
          </NativeSelect>
        </div>
      </div>
      {setting.error && (
        <p className="field-error" role="alert">
          {apiErrorMessage(i18n, setting.error)}
        </p>
      )}
    </div>
  )
}

/** One Plan: its name, limits, interval, and who has it, with Edit and Remove. */
function PlanItem({
  plan,
  intervals,
  opened,
  onOpen,
  commands,
  onRemoved,
}: {
  plan: PlanSummary
  intervals: SyncInterval[]
  opened: Opened
  onOpen: Open
  commands: PlanCommands
  /** Moves focus on once the Plan's row is gone. */
  onRemoved: () => void
}) {
  const i18n = useI18n()
  const { t } = i18n
  const editButton = useRef<HTMLButtonElement>(null)
  const removeButton = useRef<HTMLButtonElement>(null)
  const mine = opened !== null && opened.action !== "add" && opened.key === plan.key
  const editing = mine && opened.action === "edit"
  const removing = mine && opened.action === "remove"
  const { change } = commands

  function close(toggle: RefObject<HTMLButtonElement | null>) {
    onOpen(null)
    toggle.current?.focus()
  }

  return (
    <div className="setting-item">
      <div className="setting-row">
        <div className="setting-copy">
          <h3>{plan.name}</h3>
          {plan.is_default && <Badge variant="neutral">{t("settings.plans.isDefault")}</Badge>}
          <p>{planLimitsSummary(i18n, plan.limits)}</p>
          <p>{intervalLabel(i18n, plan.limits.sync_interval)}</p>
          <p>{t("settings.plans.people", { count: plan.people })}</p>
        </div>
        <div className="setting-form-actions">
          <Button
            ref={editButton}
            type="button"
            variant="outline"
            aria-expanded={editing}
            aria-controls={`plan-edit-${plan.key}`}
            onClick={() => onOpen({ action: "edit", key: plan.key })}
          >
            {t("settings.plans.edit")}
          </Button>
          <Button
            ref={removeButton}
            type="button"
            variant="ghost"
            aria-expanded={removing}
            aria-controls={`plan-remove-${plan.key}`}
            onClick={() => onOpen({ action: "remove", key: plan.key })}
          >
            {t("settings.plans.remove")}
          </Button>
        </div>
      </div>
      {editing && (
        <div id={`plan-edit-${plan.key}`}>
          <PlanEditor
            plan={plan}
            intervals={intervals}
            pending={change.isPending}
            error={change.error}
            onSave={({ name, limits }) =>
              change.mutate({ key: plan.key, payload: { name, limits } }, { onSuccess: () => close(editButton) })
            }
            onCancel={() => close(editButton)}
          />
        </div>
      )}
      {removing && (
        <PlanRemoval plan={plan} commands={commands} onRemoved={onRemoved} onKeep={() => close(removeButton)} />
      )}
    </div>
  )
}

/** Remove, confirmed inline. The server refuses the default and a Plan someone has, and says why. */
function PlanRemoval({
  plan,
  commands,
  onRemoved,
  onKeep,
}: {
  plan: PlanSummary
  commands: PlanCommands
  onRemoved: () => void
  onKeep: () => void
}) {
  const i18n = useI18n()
  const { t } = i18n
  const { remove } = commands
  return (
    <>
      <DestructiveConfirmation
        id={`plan-remove-${plan.key}`}
        title={t("settings.plans.removeConfirm.title", { name: plan.name })}
        body={t("settings.plans.removeConfirm.body")}
        cancelLabel={t("settings.plans.removeConfirm.keep")}
        confirmLabel={t("settings.plans.removeConfirm.confirm")}
        pendingLabel={t("settings.plans.removeConfirm.pending")}
        pending={remove.isPending}
        onConfirm={() => remove.mutate(plan.key, { onSuccess: onRemoved })}
        onCancel={onKeep}
      />
      {remove.error && (
        <p className="field-error" role="alert">
          {apiErrorMessage(i18n, remove.error)}
        </p>
      )}
    </>
  )
}

/** "Add a plan", and its inline form once opened. */
function AddPlanItem({
  intervals,
  adding,
  onOpen,
  commands,
  addButton,
}: {
  intervals: SyncInterval[]
  adding: boolean
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
      <div className="setting-row">
        <Button
          ref={addButton}
          type="button"
          variant="outline"
          aria-expanded={adding}
          aria-controls="plan-edit-new"
          onClick={() => onOpen({ action: "add" })}
        >
          <Plus aria-hidden="true" />
          {t("settings.plans.add")}
        </Button>
      </div>
      {adding && (
        <div id="plan-edit-new">
          <PlanEditor
            plan={null}
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
