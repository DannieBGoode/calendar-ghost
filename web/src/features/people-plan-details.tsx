import type { RefObject } from "react"

import { useToast } from "@/components/ui/toast-context"
import { PlanRemoval } from "@/features/people-plan-removal"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import type { PlanSummary, PlansOverview } from "@/lib/api"
import { removable, switchedBy } from "@/lib/plans-catalog"
import type { PlanWorkControls } from "@/lib/use-plan-work"
import type { PlanCommands } from "@/lib/use-plans"

/** What the row under a Plan's row needs: the Plan's row, to return focus to its More actions. */
type PlanDetailsProps = {
  plan: PlanSummary
  removing: boolean
  columns: number
  row: RefObject<HTMLTableRowElement | null>
  overview: PlansOverview
  commands: PlanCommands
  work: PlanWorkControls
}

/**
 * What a Plan's row has open under it: the confirmation of its removal, which returns focus to
 * More actions, and why a command from the row was refused, as Make default, or a removal once the
 * Plans read again show someone has the Plan.
 */
export function PlanDetails({ plan, removing, columns, row, overview, commands, work }: PlanDetailsProps) {
  const i18n = useI18n()
  const toasts = useToast()
  const confirming = removing && removable(plan)
  const refused = removalRefusal(commands, plan.key, confirming) ?? rowRefusal(commands, overview, plan.key)
  if (!confirming && !refused) return null
  const toMenu = () => row.current?.querySelector<HTMLButtonElement>("[aria-haspopup='menu']")?.focus()
  return (
    <tr role="row" className="plan-details-row">
      <td role="cell" colSpan={columns}>
        {confirming && (
          <PlanRemoval
            plan={plan}
            commands={commands}
            onLeft={toMenu}
            onRemoved={() => {
              toasts.show({ message: i18n.t("people.plans.results.removed", { name: plan.name }) })
              work.removed()
            }}
            onKeep={() => {
              work.closeRemoval()
              toMenu()
            }}
          />
        )}
        {refused && (
          <p className="field-error" role="alert">
            {apiErrorMessage(i18n, refused)}
          </p>
        )}
      </td>
    </tr>
  )
}

/** Why removing the Plan was refused, once its confirmation, which shows it otherwise, no longer holds. */
function removalRefusal({ remove }: PlanCommands, key: string, confirming: boolean): Error | null {
  return remove.error && remove.variables === key && !confirming ? remove.error : null
}

/**
 * Why another command from a Plan's row was refused, to show under it: Make default, which the
 * switch's refusal is not, nor Undo's, which shows in a toast.
 */
function rowRefusal({ setting }: PlanCommands, overview: PlansOverview, key: string): Error | null {
  if (setting.error && !setting.variables.undo && !switchedBy(setting.variables, overview) && setting.variables.defaultPlan === key) {
    return setting.error
  }
  return null
}
