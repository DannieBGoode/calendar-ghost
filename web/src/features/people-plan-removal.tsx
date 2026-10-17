import { DestructiveConfirmation } from "@/components/destructive-confirmation"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import type { PlanSummary } from "@/lib/api"
import type { PlanCommands } from "@/lib/use-plans"

/**
 * What Remove opens under a Plan nobody has and that is not the default: it asks inline, and a
 * refusal from a change made meanwhile, as when someone was given the Plan, shows under the
 * confirmation. Remove on any other Plan is disabled in its menu, which says why.
 */
export function PlanRemoval({
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
        title={t("people.plans.removeConfirm.title", { name: plan.name })}
        body={t("people.plans.removeConfirm.body")}
        cancelLabel={t("people.plans.removeConfirm.keep")}
        confirmLabel={t("people.plans.removeConfirm.confirm")}
        pendingLabel={t("people.plans.removeConfirm.pending")}
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
