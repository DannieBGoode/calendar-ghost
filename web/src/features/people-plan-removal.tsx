import { Info } from "lucide-react"
import { useEffect, useRef } from "react"

import { DestructiveConfirmation } from "@/components/destructive-confirmation"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import type { PlanSummary } from "@/lib/api"
import type { PlanCommands } from "@/lib/use-plans"

/**
 * What Remove opens under a Plan that is not the default. For a Plan someone has, it says at once
 * how many people have it and what to do, since the server would refuse; otherwise it asks inline,
 * and a refusal from a change made meanwhile shows under the confirmation.
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
  if (plan.people > 0) return <PlanInUse plan={plan} />
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

/** Why a Plan people have cannot be removed yet. It takes focus as it opens, so it is read at once. */
function PlanInUse({ plan }: { plan: PlanSummary }) {
  const { t } = useI18n()
  const note = useRef<HTMLDivElement>(null)
  useEffect(() => {
    note.current?.focus()
  }, [])
  return (
    <div id={`plan-remove-${plan.key}`} ref={note} className="plan-in-use" tabIndex={-1}>
      <Info aria-hidden="true" />
      <p>{t("people.plans.inUse", { count: plan.people, name: plan.name })}</p>
    </div>
  )
}
