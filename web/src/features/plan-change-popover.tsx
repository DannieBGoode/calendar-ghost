import { Popover } from "@/components/ui/popover"
import { ChooserWithPlans, type PlanChooserProps, type SaveChange } from "@/features/plan-change"
import type { PlanChanges } from "@/features/use-plan-changes"
import { useI18n } from "@/i18n/provider"
import { changeTitle, type PlanPerson } from "@/lib/plan-change"
import type { PeopleCommands } from "@/lib/use-people"

/** Where focus waits in Everyone once the control that opened Change plan is gone: the list's heading. */
export const LIST_TITLE = "people-list-title"

type ChangePopoverProps = Omit<PlanChooserProps, "overview" | "level" | "onCancel"> & {
  open: boolean
  /** It lines up with its control's end edge, as for a control at the end of a row. */
  alignEnd?: boolean
  /** The control that opened it, which gets focus back as it closes. */
  returnFocus: () => HTMLElement | null
  /** Escape, Cancel, or a press outside asks to close it. */
  onClose: () => void
}

/**
 * Change plan in a popover beside the control that opened it, for the people selected in Everyone
 * or one person's row there. It stays inside the window: above its control when there is more room
 * there, its options scrolling inside it while its title and Save stay in view.
 */
export function ChangePlanPopover({ open, alignEnd, returnFocus, onClose, ...chooser }: ChangePopoverProps) {
  return (
    <Popover
      id={`${chooser.id}-popover`}
      open={open}
      alignEnd={alignEnd}
      aria-labelledby={`${chooser.id}-title`}
      returnFocus={returnFocus}
      onClose={onClose}
      className="plan-change-popover"
    >
      <ChooserWithPlans {...chooser} onCancel={onClose} />
    </Popover>
  )
}

/**
 * Change plan for one person from their row in Everyone, open while their row's command is Change
 * plan. Once the change is made, focus returns to their row's actions, or to the list's heading
 * when the change took them out of a narrowed list, and the list's toast says what it did.
 */
export function RowPlanPopover({
  person,
  commands,
  changes,
  returnFocus,
}: {
  person: PlanPerson
  commands: PeopleCommands
  changes: PlanChanges
  returnFocus: () => HTMLElement | null
}) {
  const i18n = useI18n()
  const source = person.id
  const refusal = changes.refusalFor(source)
  const save: SaveChange = (plan, chosen) =>
    changes.change({
      source,
      people: [person],
      plan,
      chosen,
      done: (show) => {
        commands.closePlanChoice()
        const control = returnFocus()
        ;(control?.isConnected ? control : document.getElementById(LIST_TITLE))?.focus()
        show()
      },
    })
  const close = () => {
    if (changes.pending) return
    changes.forget()
    commands.closePlanChoice()
  }
  return (
    <ChangePlanPopover
      id={`plan-change-${person.id}`}
      title={changeTitle(i18n, [person])}
      open={commands.choosingPlan === person.id}
      alignEnd
      people={[person]}
      pending={changes.pending}
      refusal={refusal}
      returnFocus={returnFocus}
      onChoose={() => refusal && changes.forget()}
      onSave={save}
      onClose={close}
    />
  )
}
