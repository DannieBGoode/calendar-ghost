import { Info } from "lucide-react"
import { useEffect, useRef } from "react"

import { DestructiveConfirmation } from "@/components/destructive-confirmation"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import type { PlanSummary } from "@/lib/api"
import { appPathForPeopleTab, isPlainLeftClick } from "@/lib/navigation"
import { DEFAULT_PEOPLE_QUERY, peopleSearch } from "@/lib/people-query"
import { planInUseText } from "@/lib/plans"
import { usePlanHolders, type PlanCommands } from "@/lib/use-plans"

/** Opens Everyone, listing who has the Plan with this key. */
export type ShowHolders = (plan: string) => void

/**
 * What Remove opens under a Plan that is not the default. For a Plan someone has, it says at once
 * who has it and what to do, since the server would refuse; otherwise it asks inline, and a
 * refusal from a change made meanwhile shows under the confirmation.
 */
export function PlanRemoval({
  plan,
  commands,
  onShowHolders,
  onRemoved,
  onKeep,
}: {
  plan: PlanSummary
  commands: PlanCommands
  onShowHolders: ShowHolders
  onRemoved: () => void
  onKeep: () => void
}) {
  const i18n = useI18n()
  const { t } = i18n
  const { remove } = commands
  if (plan.people > 0) return <PlanInUse plan={plan} onShowHolders={onShowHolders} />
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

/**
 * Why a Plan people have cannot be removed yet, naming the first three who have it, by email, and
 * then how many more, with a link to Everyone listing them all, where each one's Plan can change.
 * It takes focus as it opens, so it is read at once; until the names arrive it counts them, and
 * says them again once they do.
 */
function PlanInUse({ plan, onShowHolders }: { plan: PlanSummary; onShowHolders: ShowHolders }) {
  const i18n = useI18n()
  const holders = usePlanHolders(plan.key)
  const note = useRef<HTMLDivElement>(null)
  useEffect(() => {
    note.current?.focus()
  }, [])
  const href = `${appPathForPeopleTab("everyone")}${peopleSearch({ ...DEFAULT_PEOPLE_QUERY, plan: plan.key })}`
  return (
    <div id={`plan-remove-${plan.key}`} ref={note} className="plan-in-use" tabIndex={-1}>
      <Info aria-hidden="true" />
      <div className="plan-in-use-copy">
        <p aria-live="polite">{planInUseText(i18n, plan, holders.data)}</p>
        <a
          className="text-link"
          href={href}
          onClick={(event) => {
            if (!isPlainLeftClick(event)) return
            event.preventDefault()
            onShowHolders(plan.key)
          }}
        >
          {i18n.t("people.plans.inUseShow", { name: plan.name })}
        </a>
      </div>
    </div>
  )
}
