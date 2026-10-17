import { ChevronDown } from "lucide-react"
import { useRef, useState } from "react"

import { Button } from "@/components/ui/button"
import { useToast } from "@/components/ui/toast-context"
import { ChangePlanPopover } from "@/features/person-plan"
import type { ConfirmChange } from "@/features/plan-change"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import type { PersonRow } from "@/lib/api"
import { changedResult, restoredResult, undoMoves } from "@/lib/plan-assignment"
import { useGivePlans } from "@/lib/use-people"

/** Where focus waits once the selected people are done with: the list's heading. */
const LIST_TITLE = "people-list-title"
/** The box in the table's header that selects everyone on the page. */
export const SELECT_ALL = "people-select-all"

/**
 * The bar above Everyone's table for the people selected on this page: how many, Change plan, which
 * opens a popover of Plans with a dry run, and Clear selection. With nobody selected it says what
 * selecting is for, in the same place, so the table never moves as the first row is selected. A
 * change answers in a toast with Undo, which gives each person back the Plan they had; the
 * selection is then done with, and focus waits on the list's heading. While any command on people
 * runs, Change plan waits.
 */
export function PeopleBulkBar({
  selected,
  busy,
  onClear,
}: {
  selected: readonly PersonRow[]
  /** A command on someone is on its way. */
  busy: boolean
  /** Selects nobody: after Clear selection, or once a change is made. */
  onClear: () => void
}) {
  const i18n = useI18n()
  const { t } = i18n
  const toasts = useToast()
  const give = useGivePlans()
  const undo = useGivePlans()
  const [open, setOpen] = useState(false)
  const trigger = useRef<HTMLButtonElement>(null)

  const close = () => {
    if (give.isPending) return
    give.reset()
    setOpen(false)
  }

  // The button goes with the selection, so focus moves to the box that selects the page.
  const clear = () => {
    if (give.isPending) return
    setOpen(false)
    onClear()
    document.getElementById(SELECT_ALL)?.focus()
  }

  const confirm: ConfirmChange = (plan, chosen) => {
    const people = [...selected]
    give.mutate([{ plan, userIds: people.map((person) => person.id) }], {
      onSuccess: ([answer]) => {
        // Focus waits on the list's heading before the bar goes back to rest, so the toast's Undo
        // and Close return it there.
        document.getElementById(LIST_TITLE)?.focus()
        setOpen(false)
        onClear()
        undo.reset()
        toasts.show({
          message: changedResult(i18n, people, plan === null ? null : chosen),
          action: answer && {
            label: t("common.toast.undo"),
            onSelect: () => undo.mutate(undoMoves(answer), { onSuccess: () => toasts.show({ message: restoredResult(i18n, answer) }) }),
          },
        })
      },
    })
  }

  return (
    <div className="people-bulk-bar" role="region" aria-label={t("people.bulk.label")} data-active={selected.length > 0}>
      {selected.length === 0 ? (
        <p className="people-bulk-rest">{t("people.bulk.rest")}</p>
      ) : (
        <>
          <span className="people-bulk-count">{t("people.bulk.selected", { count: selected.length })}</span>
          <div className="people-bulk-change">
            <Button
              ref={trigger}
              type="button"
              variant="outline"
              size="sm"
              aria-haspopup="dialog"
              aria-expanded={open}
              aria-controls={open ? "plan-change-bulk-popover" : undefined}
              aria-disabled={busy || undefined}
              onClick={() => (open ? close() : !busy && setOpen(true))}
            >
              {t("people.bulk.change")}
              <ChevronDown aria-hidden="true" />
            </Button>
            <ChangePlanPopover
              id="plan-change-bulk"
              open={open}
              people={selected}
              pending={give.isPending}
              refusal={give.error}
              returnFocus={() => trigger.current}
              onChoose={() => give.error && give.reset()}
              onConfirm={confirm}
              onClose={close}
            />
          </div>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="people-bulk-clear"
            aria-disabled={give.isPending || undefined}
            onClick={clear}
          >
            {t("people.bulk.clear")}
          </Button>
        </>
      )}
      {undo.error && (
        <p className="field-error people-bulk-error" role="alert">
          {apiErrorMessage(i18n, undo.error)}
        </p>
      )}
    </div>
  )
}
