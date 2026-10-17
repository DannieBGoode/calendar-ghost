import { useEffect, useRef, useState, type KeyboardEvent, type RefObject, type SyntheticEvent } from "react"

import { Button } from "@/components/ui/button"
import { NameField, PlanLimitField, SpeedField } from "@/features/plan-editor-fields"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import type { ApiError, PlanChange, PlanSummary, SyncInterval } from "@/lib/api"
import { useLeaveQuestion, type LeaveQuestion } from "@/lib/leave-guard"
import {
  COUNT_LIMIT,
  LIMIT_MINIMUM,
  LIMIT_NAMES,
  LIMIT_WORDS,
  changedFields,
  draftOf,
  missingField,
  nameRefusal,
  payloadOf,
  peopleOver,
  refusedField,
  type DraftField,
  type LimitName,
  type PlanDraft,
} from "@/lib/plan-draft"

/**
 * Moves focus to one of the editor's fields, found by the `data-field` it carries: the field
 * itself, or the radio chosen in a group of them, as Sync speed is.
 */
function focusField(form: HTMLFormElement | null, field: DraftField) {
  const target = form?.querySelector<HTMLElement>(`[data-field='${field}']`)
  if (!target || target instanceof HTMLInputElement) {
    target?.focus()
    return
  }
  ;(target.querySelector<HTMLElement>("input:checked") ?? target.querySelector<HTMLElement>("input"))?.focus()
}

/**
 * A refusal of the last save, or one found before sending, as for a name another Plan has: the
 * field it names, which takes focus as it arrives and again at each Save it stops, and its
 * message. Changing that field puts the refusal away; one that names no field stays until the
 * next save.
 */
function useRefusal(error: unknown, draft: PlanDraft, form: RefObject<HTMLFormElement | null>) {
  const i18n = useI18n()
  const [sent, setSent] = useState<PlanDraft | null>(null)
  const [dismissed, setDismissed] = useState<unknown>(null)
  const [found, setFound] = useState<ApiError | null>(null)
  const shown = found ?? (error && error !== dismissed ? error : null)
  const field = shown ? refusedField(shown, found ? draft : (sent ?? draft)) : null
  useEffect(() => {
    if (field !== null) focusField(form.current, field)
  }, [shown, field, form])
  return {
    field,
    message: shown ? apiErrorMessage(i18n, shown) : null,
    /** Remembers the draft a save sends, so its refusal names a field of that draft. */
    sending: (next: PlanDraft) => {
      setFound(null)
      setSent(next)
    },
    /** Shows a refusal found before sending, as the server would answer it. */
    found: setFound,
    changed: (next: Partial<PlanDraft>) => {
      if (field === null || !(field in next)) return
      setDismissed(error)
      setFound(null)
    },
  }
}

/**
 * The form in a Plan's panel that adds a Plan or changes one: its name, then its limits for each
 * person, each No limit or Up to a whole number, and for Integration Tokens None, then how soon
 * calendars sync, and a footer with Save plan, Cancel, and how many changes are not saved. It asks
 * for no key: the server makes a new Plan's from its name. While a save is on its way, every
 * control keeps its focus but ignores changes; a refusal moves focus to the field it names, and so
 * does a name another Plan already has, before anything is sent. A limit lower than the people on
 * the Plan use says how many of them it would leave with more than it allows. While changes are
 * not saved, leaving the form in any way, Cancel, Close, Escape, another Plan, a tab, another page,
 * or Back, first asks in the footer whether to discard them.
 */
export function PlanEditor({
  plan,
  start,
  enabled,
  others,
  intervals,
  pending,
  error,
  onSave,
  onCancel,
}: {
  plan: PlanSummary | null
  /** How a new Plan starts, such as a copy of another; empty, with no limits, unless given. */
  start?: PlanDraft | undefined
  /** Plans limit people now, so a lower limit's warning says what it does now, not once they are on. */
  enabled: boolean
  /** The names of every other Plan, which this one's may not read as. */
  others: readonly string[]
  intervals: SyncInterval[]
  pending: boolean
  error: unknown
  onSave: (payload: PlanChange) => void
  onCancel: () => void
}) {
  const { t } = useI18n()
  const [draft, setDraft] = useState(() => (plan === null && start ? start : draftOf(plan, intervals)))
  const form = useRef<HTMLFormElement>(null)
  const refusal = useRefusal(error, draft, form)
  const id = plan ? `plan-${plan.key}` : "plan-new"
  // What the Plan has saved, or how a new one started, so the footer counts what changed since.
  const saved = plan === null && start ? start : draftOf(plan, intervals)
  const changes = changedFields(draft, saved)
  const leaving = useLeaveQuestion(changes > 0)
  const errorOf = (field: DraftField) => (refusal.field === field ? refusal.message : null)
  const warningOf = (name: LimitName) => {
    const count = plan ? peopleOver(plan, draft, name) : 0
    const words = LIMIT_WORDS[name]
    return count > 0 ? t(enabled ? words.lowered : words.loweredLater, { count, name: plan?.name ?? "" }) : ""
  }

  function change(next: Partial<PlanDraft>) {
    if (pending) return
    refusal.changed(next)
    setDraft((current) => ({ ...current, ...next }))
  }

  /** Drops the changes, returns focus where it was as the question came, and leaves. */
  function discard() {
    setDraft(saved)
    focusBack(leaving.asking?.from ?? null)
    leaving.discard()
  }

  /** Keeps the changes, with focus back where it was, or on Save. */
  function keep() {
    const from = leaving.asking?.from ?? null
    leaving.keep()
    if (!focusBack(from)) form.current?.querySelector<HTMLElement>("button[type='submit']")?.focus()
  }

  function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    const payload = payloadOf(draft)
    if (!payload || pending) return
    const taken = nameRefusal(draft, others)
    if (taken) {
      refusal.found(taken)
      return
    }
    refusal.sending(draft)
    onSave(payload)
  }

  return (
    <form ref={form} id={`${id}-form`} className="plan-panel-form" noValidate onSubmit={submit}>
      <div className="plan-panel-body">
        <NameField id={id} value={draft.name} pending={pending} error={errorOf("name")} onChange={(name) => change({ name })} />
        <fieldset className="plan-limits">
          <legend>{t("people.plans.editor.limitsLegend")}</legend>
          {LIMIT_NAMES.map((name) => (
            <PlanLimitField
              key={name}
              id={id}
              name={name}
              limit={draft[name]}
              pending={pending}
              error={errorOf(name)}
              warning={warningOf(name)}
              onChange={(limit) => change({ [name]: limit })}
            />
          ))}
          <SpeedField
            id={id}
            intervals={intervals}
            value={draft.interval}
            pending={pending}
            error={errorOf("interval")}
            onChange={(interval) => change({ interval })}
          />
        </fieldset>
      </div>
      {leaving.asking ? (
        <LeaveQuestionBar id={id} asking={leaving.asking} changes={changes} onKeep={keep} onDiscard={discard} />
      ) : (
        <EditorFooter
          id={id}
          missing={missingField(draft)}
          changes={changes}
          pending={pending}
          refusal={refusal.field === null ? refusal.message : null}
          onCancel={onCancel}
        />
      )}
    </form>
  )
}

/** Moves focus back to an element still on the page, other than the page itself; says if it did. */
function focusBack(from: Element | null): boolean {
  if (!(from instanceof HTMLElement) || !from.isConnected || from === document.body) return false
  from.focus()
  return true
}

/**
 * The footer's question before the page leaves the form with changes not saved: how many it would
 * discard, Keep editing, which takes focus as it asks, and Discard. Escape keeps editing.
 */
function LeaveQuestionBar({
  id,
  asking,
  changes,
  onKeep,
  onDiscard,
}: {
  id: string
  asking: LeaveQuestion
  changes: number
  onKeep: () => void
  onDiscard: () => void
}) {
  const { t } = useI18n()
  const keep = useRef<HTMLButtonElement>(null)
  const titleId = `${id}-leave-title`
  useEffect(() => {
    keep.current?.focus()
  }, [asking])

  function escape(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "Escape") return
    event.preventDefault()
    onKeep()
  }

  return (
    <div className="plan-panel-foot plan-panel-question" role="group" aria-labelledby={titleId} onKeyDown={escape}>
      <p id={titleId} className="plan-panel-question-title">
        {t("people.plans.editor.leave.question", { count: changes })}
      </p>
      <div className="plan-panel-actions">
        <Button ref={keep} type="button" variant="outline" onClick={onKeep}>
          {t("people.plans.editor.leave.keep")}
        </Button>
        <Button type="button" variant="destructive" onClick={onDiscard}>
          {t("people.plans.editor.leave.discard")}
        </Button>
      </div>
    </div>
  )
}

/**
 * Save and Cancel, then how many changes are not saved. Neither button is ever natively disabled,
 * so focus stays on them while a save is on its way; Save names the field it waits for, and
 * Cancel waits for Save, so its answer has a form to show in. A refusal that names no field shows
 * under them.
 */
function EditorFooter({
  id,
  missing,
  changes,
  pending,
  refusal,
  onCancel,
}: {
  id: string
  missing: "name" | LimitName | null
  changes: number
  pending: boolean
  refusal: string | null
  onCancel: () => void
}) {
  const { t } = useI18n()
  const reasonId = `${id}-save-reason`
  return (
    <div className="plan-panel-foot">
      <div className="plan-panel-actions">
        <Button
          type="submit"
          aria-disabled={missing !== null || pending || undefined}
          aria-busy={pending || undefined}
          aria-describedby={missing ? reasonId : undefined}
        >
          {t("people.plans.editor.save")}
        </Button>
        <Button type="button" variant="ghost" aria-disabled={pending || undefined} onClick={() => !pending && onCancel()}>
          {t("people.plans.editor.cancel")}
        </Button>
        {changes > 0 && (
          <span className="plan-panel-status plan-panel-changes">{t("people.plans.editor.changes", { count: changes })}</span>
        )}
      </div>
      {missing && (
        <p id={reasonId} className="field-hint">
          {missing === "name"
            ? t("people.plans.editor.missing.name")
            : t(LIMIT_WORDS[missing].missing, { min: LIMIT_MINIMUM[missing], max: COUNT_LIMIT })}
        </p>
      )}
      {refusal && (
        <p className="field-error" role="alert">
          {refusal}
        </p>
      )}
    </div>
  )
}
