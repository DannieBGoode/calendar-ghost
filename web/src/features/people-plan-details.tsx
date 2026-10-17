import type { RefObject } from "react"

import { useToast } from "@/components/ui/toast-context"
import { PlanRemoval } from "@/features/people-plan-removal"
import { PlanAssign } from "@/features/plan-assign"
import { PlanEditor } from "@/features/plan-editor"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import type { PlanAssignments, PlanSummary, PlansOverview, SyncInterval } from "@/lib/api"
import { assignedResult, restoredResult, undoMoves } from "@/lib/plan-assignment"
import { switchedBy } from "@/lib/plans-catalog"
import type { PlanWorkControls } from "@/lib/use-plan-work"
import type { PlanCommands } from "@/lib/use-plans"

/** What a Plan's row can open under it. */
type PlanOpen = "edit" | "assign" | "remove"

/** What the row under a Plan's row needs: the Plan's row and name, to return focus to. */
type PlanDetailsProps = {
  plan: PlanSummary
  open: PlanOpen | null
  columns: number
  row: RefObject<HTMLTableRowElement | null>
  name: RefObject<HTMLButtonElement | null>
  overview: PlansOverview
  commands: PlanCommands
  work: PlanWorkControls
  currentUserId: string
}

/**
 * What a Plan's row has open under it: its form, which returns focus to its name as it closes;
 * Assign people or the confirmation of its removal, which return focus to More actions; and why a
 * command from the row was refused, as Make default or the Undo of Assign people.
 */
export function PlanDetails({ plan, open, columns, row, ...context }: PlanDetailsProps) {
  const i18n = useI18n()
  const refused = rowRefusal(context.commands, context.overview, plan.key, open)
  if (open === null && !refused) return null
  const toMenu = () => row.current?.querySelector<HTMLButtonElement>("[aria-haspopup='menu']")?.focus()
  return (
    <tr role="row" className="plan-details-row">
      <td role="cell" colSpan={columns}>
        {open === "edit" && <EditPlan plan={plan} {...context} />}
        {open === "assign" && <AssignPeople plan={plan} toMenu={toMenu} {...context} />}
        {open === "remove" && <RemovePlan plan={plan} toMenu={toMenu} {...context} />}
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
 * refusal is not, or the Undo of Assign people once it is closed.
 */
function rowRefusal(commands: PlanCommands, overview: PlansOverview, key: string, open: PlanOpen | null): Error | null {
  const { setting, assign } = commands
  if (setting.error && !switchedBy(setting.variables, overview) && setting.variables.defaultPlan === key) {
    return setting.error
  }
  return assign.error && open !== "assign" && assign.variables.from === key ? assign.error : null
}

type Context = Omit<PlanDetailsProps, "open" | "columns" | "row">

function EditPlan({ plan, overview, commands, work, name }: Context) {
  const i18n = useI18n()
  const toasts = useToast()
  const { change } = commands
  const close = () => {
    work.close()
    name.current?.focus()
  }
  return (
    <div id={`plan-edit-${plan.key}`}>
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
              onSuccess: (saved) => {
                // Focus leaves the form first, so the toast's Close returns it to the Plan's name.
                close()
                toasts.show({ message: i18n.t("people.plans.results.changed", { name: saved.name }) })
              },
            },
          )
        }
        onCancel={close}
      />
    </div>
  )
}

/**
 * Assign people, under the Plan's row. Once the Plan is given, a toast says to whom, with Undo,
 * which gives each person back the Plan they had and says so.
 */
function AssignPeople({ plan, overview, commands, work, currentUserId, toMenu }: Context & { toMenu: () => void }) {
  const i18n = useI18n()
  const toasts = useToast()
  const { assign } = commands
  const close = () => {
    work.close()
    toMenu()
  }
  const undo = (answer: PlanAssignments) =>
    assign.mutate(
      { from: plan.key, moves: undoMoves(answer) },
      { onSuccess: () => toasts.show({ message: restoredResult(i18n, answer) }) },
    )
  return (
    <PlanAssign
      plan={plan}
      enabled={overview.enabled}
      currentUserId={currentUserId}
      assign={assign}
      onGiven={(answer) => {
        // Focus moves to More actions first, so Undo and Close return it there.
        close()
        toasts.show({
          message: assignedResult(i18n, answer, plan.name),
          action: { label: i18n.t("common.toast.undo"), onSelect: () => undo(answer) },
        })
      }}
      onCancel={close}
    />
  )
}

function RemovePlan({ plan, commands, work, toMenu }: Context & { toMenu: () => void }) {
  const i18n = useI18n()
  const toasts = useToast()
  return (
    <PlanRemoval
      plan={plan}
      commands={commands}
      onRemoved={() => {
        toasts.show({ message: i18n.t("people.plans.results.removed", { name: plan.name }) })
        work.closeToNew()
      }}
      onKeep={() => {
        work.close()
        toMenu()
      }}
    />
  )
}

/** The offered intervals, plus a Plan's own when a later release saved one not offered here. */
function offeredWith(offered: SyncInterval[], own: SyncInterval): SyncInterval[] {
  return offered.includes(own) ? offered : [...offered, own]
}
