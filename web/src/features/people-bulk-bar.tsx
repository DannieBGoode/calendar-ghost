import { ChevronDown } from "lucide-react"
import { useRef, useState } from "react"

import { Button } from "@/components/ui/button"
import type { SaveChange } from "@/features/plan-change"
import { ChangePlanPopover, LIST_TITLE } from "@/features/plan-change-popover"
import type { PlanChanges } from "@/features/use-plan-changes"
import { useI18n } from "@/i18n/provider"
import type { PersonRow } from "@/lib/api"
import { changeTitle } from "@/lib/plan-change"

/** The box in the table's header that selects everyone on the page. */
export const SELECT_ALL = "people-select-all"
/** Which chooser made a change: the bar's, for everyone selected. */
const BULK = "bulk"

/**
 * The bar above Everyone's table for the people selected on this page: how many, Change plan, which
 * opens a popover of Plans with a dry run, and Clear selection. With nobody selected it says what
 * selecting is for, in the same place, so the table never moves as the first row is selected. A
 * change answers through `changes`, the list's, whose toast with Undo outlasts the bar; the
 * selection is then done with, and focus waits on the list's heading. While any command on people
 * runs, Change plan waits.
 */
export function PeopleBulkBar({
  selected,
  busy,
  changes,
  onClear,
}: {
  selected: readonly PersonRow[]
  /** A command on someone is on its way. */
  busy: boolean
  /** Changes the plans of the people selected, and says what it did. */
  changes: PlanChanges
  /** Selects nobody: after Clear selection, or once a change is made. */
  onClear: () => void
}) {
  const i18n = useI18n()
  const { t } = i18n
  const [open, setOpen] = useState(false)
  const trigger = useRef<HTMLButtonElement>(null)
  const refusal = changes.refusalFor(BULK)

  const close = () => {
    if (changes.pending) return
    changes.forget()
    setOpen(false)
  }

  // The button goes with the selection, so focus moves to the box that selects the page.
  const clear = () => {
    if (changes.pending) return
    setOpen(false)
    onClear()
    document.getElementById(SELECT_ALL)?.focus()
  }

  const save: SaveChange = (plan, chosen) =>
    changes.change({
      source: BULK,
      people: [...selected],
      plan,
      chosen,
      // Focus waits on the list's heading before the bar goes back to rest, so the toast's Undo
      // and Close return it there.
      done: (show) => {
        document.getElementById(LIST_TITLE)?.focus()
        setOpen(false)
        onClear()
        show()
      },
    })

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
              title={changeTitle(i18n, selected)}
              open={open}
              people={selected}
              pending={changes.pending}
              refusal={refusal}
              returnFocus={() => trigger.current}
              onChoose={() => refusal && changes.forget()}
              onSave={save}
              onClose={close}
            />
          </div>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="people-bulk-clear"
            aria-disabled={changes.pending || undefined}
            onClick={clear}
          >
            {t("people.bulk.clear")}
          </Button>
        </>
      )}
    </div>
  )
}
