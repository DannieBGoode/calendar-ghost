import { Clock, TriangleAlert, Zap } from "lucide-react"

import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { LimitField } from "@/components/ui/limit-field"
import { RadioCards } from "@/components/ui/radio-cards"
import { useI18n } from "@/i18n/provider"
import type { SyncInterval } from "@/lib/api"
import { COUNT_LIMIT, LIMIT_MINIMUM, LIMIT_WORDS, type LimitDraft, type LimitName } from "@/lib/plan-draft"
import { describedBy } from "@/lib/utils"

/** A refusal under the field it names, announced as it appears. */
function FieldError({ id, text }: { id: string; text: string | null }) {
  if (!text) return null
  return (
    <p id={id} className="field-error" role="alert">
      {text}
    </p>
  )
}

/** The Plan's name, which people see in Your plan. */
export function NameField({
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
    <div className="plan-field field-stack">
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
        aria-describedby={describedBy(`${fieldId}-hint`, error && `${fieldId}-error`)}
        onChange={(event) => onChange(event.target.value)}
      />
      <p id={`${fieldId}-hint`} className="field-hint">
        {t("people.plans.editor.nameHint")}
      </p>
      <FieldError id={`${fieldId}-error`} text={error} />
    </div>
  )
}

/**
 * One limit for each person, as one choice: No limit or Up to a number, and for Integration
 * Tokens None first. A lower limit that leaves people with more than it allows warns in a status
 * that is always present, so a screen reader announces it as it appears.
 */
export function PlanLimitField({
  id,
  name,
  limit,
  pending,
  error,
  warning,
  onChange,
}: {
  id: string
  name: LimitName
  limit: LimitDraft
  pending: boolean
  error: string | null
  /** What a lower limit means for the people it leaves with more than it allows; empty when nobody. */
  warning: string
  onChange: (next: LimitDraft) => void
}) {
  const { t } = useI18n()
  const words = LIMIT_WORDS[name]
  const fieldId = `${id}-${name}`
  return (
    <div className="plan-field">
      <LimitField
        legend={t(words.label)}
        hint={t(words.hint)}
        labels={{
          noLimit: t("people.plans.editor.noLimit"),
          upTo: t("people.plans.editor.upTo"),
          none: name === "tokens" ? t("people.plans.editor.none") : undefined,
          fewer: t("people.plans.editor.fewer"),
          more: t("people.plans.editor.more"),
        }}
        unit={words.unit ? t(words.unit, { count: Number(limit.amount) || 0 }) : undefined}
        min={LIMIT_MINIMUM}
        max={COUNT_LIMIT}
        value={limit}
        pending={pending}
        inputProps={{
          id: fieldId,
          "data-field": name,
          "aria-invalid": error ? true : undefined,
          "aria-describedby": describedBy(error && `${fieldId}-error`, warning && `${fieldId}-warning`),
        }}
        onChange={onChange}
      >
        <p id={`${fieldId}-warning`} className="field-hint plan-limit-warning" data-tone="attention" role="status">
          {warning ? (
            <>
              <TriangleAlert aria-hidden="true" />
              {warning}
            </>
          ) : null}
        </p>
        <FieldError id={`${fieldId}-error`} text={error} />
      </LimitField>
    </div>
  )
}

/**
 * How soon the Plan's calendars sync, as radio cards that each say what they do, then that longer
 * intervals arrive later. `intervals` are the offered ones, plus the Plan's own when a later
 * release saved one this release does not offer.
 */
export function SpeedField({
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
  const { t } = useI18n()
  const fieldId = `${id}-interval`
  const options = intervals.map((interval) => ({
    value: interval,
    title: t(`people.plans.editor.speedTitle.${interval}`),
    description: t(`people.plans.editor.speedDescription.${interval}`),
    icon: interval === "instant" ? <Zap aria-hidden="true" /> : <Clock aria-hidden="true" />,
  }))
  return (
    <div className="plan-field plan-speed-field" data-field="interval">
      <p id={`${fieldId}-label`} className="plan-field-label">
        {t("people.plans.editor.speed")}
      </p>
      <p id={`${fieldId}-hint`} className="plan-field-hint">
        {t("people.plans.editor.speedHint")}
      </p>
      <RadioCards
        aria-labelledby={`${fieldId}-label`}
        aria-describedby={describedBy(`${fieldId}-hint`, `${fieldId}-later`, error && `${fieldId}-error`)}
        aria-invalid={error ? true : undefined}
        options={options}
        value={value}
        pending={pending}
        onValueChange={onChange}
      />
      <p id={`${fieldId}-later`} className="field-hint">
        {t("people.plans.editor.intervalHint")}
      </p>
      <FieldError id={`${fieldId}-error`} text={error} />
    </div>
  )
}
