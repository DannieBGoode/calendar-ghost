import { TriangleAlert } from "lucide-react"
import { useEffect, useRef, useState, type RefObject, type SyntheticEvent } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { NativeSelect } from "@/components/ui/native-select"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import type { MessageKey } from "@/i18n/types"
import type { PlanChange, PlanSummary, SyncInterval } from "@/lib/api"
import {
  COUNT_LIMIT,
  LIMIT_MINIMUM,
  LIMIT_NAMES,
  draftOf,
  lowers,
  missingField,
  payloadOf,
  refusedField,
  type DraftField,
  type LimitDraft,
  type LimitName,
  type PlanDraft,
} from "@/lib/plan-draft"
import { intervalLabel } from "@/lib/plans"

/** How the editor words each limit: its label, what counts, why Save waits for it, and a lowering. */
const LIMIT_WORDS: Readonly<
  Record<LimitName, { label: MessageKey; hint: MessageKey; missing: MessageKey; lowered: MessageKey }>
> = {
  rules: {
    label: "people.plans.editor.rules",
    hint: "people.plans.editor.rulesHint",
    missing: "people.plans.editor.missing.rules",
    lowered: "people.plans.editor.lowered.rules",
  },
  accounts: {
    label: "people.plans.editor.accounts",
    hint: "people.plans.editor.accountsHint",
    missing: "people.plans.editor.missing.accounts",
    lowered: "people.plans.editor.lowered.accounts",
  },
  tokens: {
    label: "people.plans.editor.tokens",
    hint: "people.plans.editor.tokensHint",
    missing: "people.plans.editor.missing.tokens",
    lowered: "people.plans.editor.lowered.tokens",
  },
}

/** Moves focus to one of the editor's fields, found by the `data-field` it carries. */
function focusField(form: HTMLFormElement | null, field: DraftField) {
  form?.querySelector<HTMLElement>(`[data-field='${field}']`)?.focus()
}

/** The ids an element's aria-describedby names, leaving out those not shown. */
function describedBy(...ids: (string | false | null | undefined)[]): string | undefined {
  return ids.filter(Boolean).join(" ") || undefined
}

/**
 * A refusal of the last save: the field it names, which takes focus as it arrives, and its
 * message. Changing that field puts the refusal away; one that names no field stays until the
 * next save.
 */
function useRefusal(error: unknown, draft: PlanDraft, form: RefObject<HTMLFormElement | null>) {
  const i18n = useI18n()
  const [sent, setSent] = useState<PlanDraft | null>(null)
  const [dismissed, setDismissed] = useState<unknown>(null)
  const shown = error && error !== dismissed ? error : null
  const field = shown ? refusedField(shown, sent ?? draft) : null
  useEffect(() => {
    if (field !== null) focusField(form.current, field)
  }, [error, field, form])
  return {
    field,
    message: shown ? apiErrorMessage(i18n, shown) : null,
    /** Remembers the draft a save sends, so its refusal names a field of that draft. */
    sending: setSent,
    changed: (next: Partial<PlanDraft>) => {
      if (field !== null && field in next) setDismissed(error)
    },
  }
}

/**
 * The inline form that adds a Plan or changes one: its name, then its limits for each person,
 * each a whole number or No limit, and how soon calendars sync. It asks for no key: the server
 * makes a new Plan's from its name. `intervals` are the offered ones, plus the Plan's own when a
 * later release saved one this release does not offer. While a save is on its way, every control
 * keeps its focus but ignores changes; a refusal moves focus to the field it names.
 */
export function PlanEditor({
  plan,
  intervals,
  pending,
  error,
  onSave,
  onCancel,
}: {
  plan: PlanSummary | null
  intervals: SyncInterval[]
  pending: boolean
  error: unknown
  onSave: (payload: PlanChange) => void
  onCancel: () => void
}) {
  const { t } = useI18n()
  const [draft, setDraft] = useState(() => draftOf(plan, intervals))
  const form = useRef<HTMLFormElement>(null)
  const refusal = useRefusal(error, draft, form)
  useEffect(() => {
    focusField(form.current, "name")
  }, [])
  const id = plan ? `plan-${plan.key}` : "plan-new"
  const errorOf = (field: DraftField) => (refusal.field === field ? refusal.message : null)

  function change(next: Partial<PlanDraft>) {
    if (pending) return
    refusal.changed(next)
    setDraft((current) => ({ ...current, ...next }))
  }

  function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    const payload = payloadOf(draft)
    if (!payload || pending) return
    refusal.sending(draft)
    onSave(payload)
  }

  return (
    <form ref={form} className="setting-form" noValidate onSubmit={submit}>
      <NameField
        id={id}
        value={draft.name}
        pending={pending}
        error={errorOf("name")}
        onChange={(name) => change({ name })}
      />
      <fieldset className="plan-limits">
        <legend>{t("people.plans.editor.limitsLegend")}</legend>
        {LIMIT_NAMES.map((name) => (
          <LimitField
            key={name}
            id={id}
            name={name}
            limit={draft[name]}
            pending={pending}
            error={errorOf(name)}
            limitedPeople={lowers(plan, draft, name) ? (plan?.limited_people ?? 0) : 0}
            onChange={(limit) => change({ [name]: limit })}
          />
        ))}
        <IntervalField
          id={id}
          intervals={intervals}
          value={draft.interval}
          pending={pending}
          error={errorOf("interval")}
          onChange={(interval) => change({ interval })}
        />
      </fieldset>
      {refusal.message && refusal.field === null && (
        <p className="field-error" role="alert">
          {refusal.message}
        </p>
      )}
      <EditorActions id={id} missing={missingField(draft)} pending={pending} onCancel={onCancel} />
    </form>
  )
}

/** A refusal under the field it names, announced as it appears. */
function FieldError({ id, text }: { id: string; text: string | null }) {
  if (!text) return null
  return (
    <p id={id} className="field-error" role="alert">
      {text}
    </p>
  )
}

function NameField({
  id,
  value,
  pending,
  error,
  onChange,
}: {
  id: string
  value: string
  pending: boolean
  error: string | null
  onChange: (name: string) => void
}) {
  const { t } = useI18n()
  const fieldId = `${id}-name`
  return (
    <div className="field-stack">
      <Label htmlFor={fieldId}>{t("people.plans.editor.name")}</Label>
      <Input
        id={fieldId}
        data-field="name"
        value={value}
        maxLength={60}
        autoComplete="off"
        readOnly={pending}
        aria-disabled={pending || undefined}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(error && `${fieldId}-error`)}
        onChange={(event) => onChange(event.target.value)}
      />
      <FieldError id={`${fieldId}-error`} text={error} />
    </div>
  )
}

/**
 * One limit for each person: No limit, or the whole number it hides while ticked. No limit comes
 * first, so the number it shows is the next stop. Lowering the limit of a Plan that limits people
 * warns in a status that is always present, so a screen reader announces it as it appears.
 */
function LimitField({
  id,
  name,
  limit,
  pending,
  error,
  limitedPeople,
  onChange,
}: {
  id: string
  name: LimitName
  limit: LimitDraft
  pending: boolean
  error: string | null
  /** How many people the Plan limits, when this limit is lowered; 0 when there is nothing to warn. */
  limitedPeople: number
  onChange: (next: LimitDraft) => void
}) {
  const { t } = useI18n()
  const words = LIMIT_WORDS[name]
  const fieldId = `${id}-${name}`
  const warning = limitedPeople > 0 ? t(words.lowered, { count: limitedPeople }) : ""
  return (
    <div role="group" aria-labelledby={`${fieldId}-label`} aria-describedby={`${fieldId}-hint`} className="field-stack">
      <Label id={`${fieldId}-label`} htmlFor={limit.unlimited ? undefined : fieldId}>
        {t(words.label)}
      </Label>
      <div className="plan-limit-entry">
        <label className="checkbox-row" htmlFor={`${fieldId}-unlimited`}>
          <input
            id={`${fieldId}-unlimited`}
            type="checkbox"
            checked={limit.unlimited}
            aria-disabled={pending || undefined}
            onChange={(event) => onChange({ ...limit, unlimited: event.target.checked })}
          />
          <span>
            <strong>{t("people.plans.editor.noLimit")}</strong>
          </span>
        </label>
        {!limit.unlimited && (
          <Input
            id={fieldId}
            data-field={name}
            type="number"
            inputMode="numeric"
            min={LIMIT_MINIMUM[name]}
            max={COUNT_LIMIT}
            step={1}
            value={limit.amount}
            readOnly={pending}
            aria-disabled={pending || undefined}
            aria-invalid={error ? true : undefined}
            aria-describedby={describedBy(error && `${fieldId}-error`, warning && `${fieldId}-warning`)}
            onChange={(event) => onChange({ ...limit, amount: event.target.value })}
          />
        )}
      </div>
      <p id={`${fieldId}-hint`} className="field-hint">
        {t(words.hint)}
      </p>
      <p id={`${fieldId}-warning`} className="field-hint" data-tone="attention" role="status">
        {warning ? (
          <>
            <TriangleAlert aria-hidden="true" />
            {warning}
          </>
        ) : null}
      </p>
      <FieldError id={`${fieldId}-error`} text={error} />
    </div>
  )
}

function IntervalField({
  id,
  intervals,
  value,
  pending,
  error,
  onChange,
}: {
  id: string
  intervals: SyncInterval[]
  value: SyncInterval
  pending: boolean
  error: string | null
  onChange: (interval: SyncInterval) => void
}) {
  const i18n = useI18n()
  const { t } = i18n
  const fieldId = `${id}-interval`
  return (
    <div className="field-stack">
      <Label htmlFor={fieldId}>{t("people.plans.editor.interval")}</Label>
      <NativeSelect
        id={fieldId}
        data-field="interval"
        value={value}
        aria-disabled={pending || undefined}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(error && `${fieldId}-error`, `${fieldId}-hint`)}
        onChange={(event) => onChange(event.target.value as SyncInterval)}
      >
        {intervals.map((interval) => (
          <option key={interval} value={interval}>
            {intervalLabel(i18n, interval)}
          </option>
        ))}
      </NativeSelect>
      <p id={`${fieldId}-hint`} className="field-hint">
        {t("people.plans.editor.intervalHint")}
      </p>
      <FieldError id={`${fieldId}-error`} text={error} />
    </div>
  )
}

/**
 * Save and Cancel. Neither is ever natively disabled, so focus stays on them while a save is on
 * its way; Save names the field it waits for, and Cancel waits for Save, so its answer has a form
 * to show in.
 */
function EditorActions({
  id,
  missing,
  pending,
  onCancel,
}: {
  id: string
  missing: "name" | LimitName | null
  pending: boolean
  onCancel: () => void
}) {
  const { t } = useI18n()
  const reasonId = `${id}-save-reason`
  return (
    <>
      <div className="setting-form-actions">
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
      </div>
      {missing && (
        <p id={reasonId} className="field-hint">
          {missing === "name"
            ? t("people.plans.editor.missing.name")
            : t(LIMIT_WORDS[missing].missing, { min: LIMIT_MINIMUM[missing], max: COUNT_LIMIT })}
        </p>
      )}
    </>
  )
}
