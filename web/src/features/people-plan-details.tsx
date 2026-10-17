import type { RefObject } from "react"

import { useToast } from "@/components/ui/toast-context"
import { PlanRemoval } from "@/features/people-plan-removal"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import type { PlanSummary, PlansOverview } from "@/lib/api"
import { switchedBy } from "@/lib/plans-catalog"
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
 * More actions, and why a command from the row was refused, as Make default, or the Undo of a Plan
 * given from its panel once the panel no longer shows it.
 */
export function PlanDetails({ plan, removing, columns, row, overview, commands, work }: PlanDetailsProps) {
  const i18n = useI18n()
  const toasts = useToast()
  const refused = rowRefusal(commands, overview, work, plan.key)
  if (!removing && !refused) return null
  const toMenu = () => row.current?.querySelector<HTMLButtonElement>("[aria-haspopup='menu']")?.focus()
  return (
    <tr role="row" className="plan-details-row">
      <td role="cell" colSpan={columns}>
        {removing && (
          <PlanRemoval
            plan={plan}
            commands={commands}
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

/**
 * Why a command from a Plan's row was refused, to show under it: Make default, which the switch's
 * refusal is not, or the Undo of a Plan given from its panel, while the panel does not show its
 * People, where that refusal shows otherwise.
 */
function rowRefusal(commands: PlanCommands, overview: PlansOverview, work: PlanWorkControls, key: string): Error | null {
  const { setting, assign } = commands
  if (setting.error && !switchedBy(setting.variables, overview) && setting.variables.defaultPlan === key) {
    return setting.error
  }
  const shown = work.panel?.plan === key && work.panel.tab === "people"
  return assign.error && !shown && assign.variables.via === "undo" && assign.variables.from === key ? assign.error : null
}
