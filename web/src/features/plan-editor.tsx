import { useEffect, useRef, useState, type RefObject, type SyntheticEvent } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { NativeSelect } from "@/components/ui/native-select"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import type { PlanPayload, PlanSummary, SyncInterval } from "@/lib/api"
import { intervalLabel } from "@/lib/plans"

/** One limit as the form holds it: the number typed, or Unlimited. */
type LimitDraft = { amount: string; unlimited: boolean }

type PlanDraft = {
  key: string
  name: string
  rules: LimitDraft
  accounts: LimitDraft
  tokens: LimitDraft
  interval: SyncInterval
}

/** The largest count a limit takes, as `COUNT_LIMIT` in domain/plans.py sets it. */
const COUNT_LIMIT = 10_000

function limitDraft(limit: number | null): LimitDraft {
  return limit === null ? { amount: "", unlimited: true } : { amount: String(limit), unlimited: false }
}

/** A new Plan starts with no limits and the first offered interval; an existing one as saved. */
function draftOf(plan: PlanSummary | null, intervals: SyncInterval[]): PlanDraft {
  if (plan === null) {
    const none = limitDraft(null)
    return { key: "", name: "", rules: none, accounts: none, tokens: none, interval: intervals[0] ?? "instant" }
  }
  const { rules, connected_accounts, integration_tokens, sync_interval } = plan.limits
  return {
    key: plan.key,
    name: plan.name,
    rules: limitDraft(rules),
    accounts: limitDraft(connected_accounts),
    tokens: limitDraft(integration_tokens),
    interval: sync_interval,
  }
}

/** null for Unlimited, the whole number typed, or undefined while the field holds none. */
function limitValue({ amount, unlimited }: LimitDraft): number | null | undefined {
  if (unlimited) return null
  const value = Number(amount)
  return amount.trim() !== "" && Number.isInteger(value) ? value : undefined
}

/** What Save sends, or null while a field still needs a value. The server checks each range. */
function payloadOf(draft: PlanDraft): PlanPayload | null {
  const rules = limitValue(draft.rules)
  const accounts = limitValue(draft.accounts)
  const tokens = limitValue(draft.tokens)
  if (!draft.key.trim() || !draft.name.trim() || rules === undefined || accounts === undefined || tokens === undefined) {
    return null
  }
  return {
    key: draft.key.trim(),
    name: draft.name.trim(),
    limits: { rules, connected_accounts: accounts, integration_tokens: tokens, sync_interval: draft.interval },
  }
}

/** Whether the rule limit typed is lower than the saved one, so some people may be over it. */
function lowersRules(plan: PlanSummary | null, draft: LimitDraft): boolean {
  const next = limitValue(draft)
  if (plan === null || plan.limited_people === 0 || typeof next !== "number") return false
  return plan.limits.rules === null || next < plan.limits.rules
}

/**
 * The inline form that adds a Plan or changes one. A new Plan's key is chosen once and never
 * changes, so the form warns about it; an existing Plan shows its key read-only. Each limit is a
 * whole number or Unlimited. `intervals` are the offered ones, plus the Plan's own when a later
 * release saved one this release does not offer.
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
  onSave: (payload: PlanPayload) => void
  onCancel: () => void
}) {
  const i18n = useI18n()
  const { t } = i18n
  const [draft, setDraft] = useState(() => draftOf(plan, intervals))
  const first = useRef<HTMLInputElement>(null)
  useEffect(() => {
    first.current?.focus()
  }, [])
  const id = plan ? `plan-${plan.key}` : "plan-new"
  const payload = payloadOf(draft)
  const change = (next: Partial<PlanDraft>) => setDraft((current) => ({ ...current, ...next }))

  function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    if (payload && !pending) onSave(payload)
  }

  return (
    <form className="setting-form" onSubmit={submit}>
      <KeyField id={id} plan={plan} value={draft.key} inputRef={first} onChange={(key) => change({ key })} />
      <div className="field-stack">
        <Label htmlFor={`${id}-name`}>{t("settings.plans.editor.name")}</Label>
        <Input
          ref={plan ? first : undefined}
          id={`${id}-name`}
          value={draft.name}
          maxLength={60}
          autoComplete="off"
          onChange={(event) => change({ name: event.target.value })}
        />
      </div>
      <LimitField
        id={`${id}-rules`}
        label={t("settings.plans.editor.rules")}
        limit={draft.rules}
        minimum={1}
        onChange={(rules) => change({ rules })}
      />
      <LimitField
        id={`${id}-accounts`}
        label={t("settings.plans.editor.accounts")}
        limit={draft.accounts}
        minimum={1}
        onChange={(accounts) => change({ accounts })}
      />
      <LimitField
        id={`${id}-tokens`}
        label={t("settings.plans.editor.tokens")}
        limit={draft.tokens}
        minimum={0}
        onChange={(tokens) => change({ tokens })}
      />
      <div className="field-stack">
        <Label htmlFor={`${id}-interval`}>{t("settings.plans.editor.interval")}</Label>
        <NativeSelect
          id={`${id}-interval`}
          value={draft.interval}
          onChange={(event) => change({ interval: event.target.value as SyncInterval })}
        >
          {intervals.map((interval) => (
            <option key={interval} value={interval}>
              {intervalLabel(i18n, interval)}
            </option>
          ))}
        </NativeSelect>
      </div>
      {plan && lowersRules(plan, draft.rules) && (
        <p className="field-hint" data-tone="attention">
          {t("settings.plans.editor.lowerWarning", { count: plan.limited_people })}
        </p>
      )}
      {error ? (
        <p className="field-error" role="alert">
          {apiErrorMessage(i18n, error)}
        </p>
      ) : null}
      <div className="setting-form-actions">
        <Button type="submit" disabled={!payload || pending}>
          {t("settings.plans.editor.save")}
        </Button>
        {/* Waits for Save, as a confirmation's Cancel does, so its answer has a form to show in. */}
        <Button type="button" variant="ghost" disabled={pending} onClick={onCancel}>
          {t("settings.plans.editor.cancel")}
        </Button>
      </div>
    </form>
  )
}

/** The Plan's key: chosen once, with a warning, for a new Plan; read-only for an existing one. */
function KeyField({
  id,
  plan,
  value,
  inputRef,
  onChange,
}: {
  id: string
  plan: PlanSummary | null
  value: string
  inputRef: RefObject<HTMLInputElement | null>
  onChange: (key: string) => void
}) {
  const { t } = useI18n()
  return (
    <div className="field-stack">
      <Label htmlFor={`${id}-key`}>{t("settings.plans.editor.key")}</Label>
      {plan ? (
        <Input id={`${id}-key`} className="field-read-only" value={plan.key} readOnly />
      ) : (
        <>
          <Input
            ref={inputRef}
            id={`${id}-key`}
            value={value}
            maxLength={32}
            autoComplete="off"
            spellCheck={false}
            aria-describedby={`${id}-key-hint`}
            onChange={(event) => onChange(event.target.value)}
          />
          <p id={`${id}-key-hint`} className="field-hint">
            {t("settings.plans.editor.keyHint")}
          </p>
        </>
      )}
    </div>
  )
}

/** One limit: a whole number, or Unlimited, which leaves the number aside. */
function LimitField({
  id,
  label,
  limit,
  minimum,
  onChange,
}: {
  id: string
  label: string
  limit: LimitDraft
  /** Rules and calendar accounts allow at least 1; a Plan may offer no Integration Tokens. */
  minimum: number
  onChange: (next: LimitDraft) => void
}) {
  const { t } = useI18n()
  return (
    <div role="group" aria-labelledby={`${id}-label`} className="field-stack">
      <Label id={`${id}-label`} htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type="number"
        inputMode="numeric"
        min={minimum}
        max={COUNT_LIMIT}
        step={1}
        value={limit.amount}
        disabled={limit.unlimited}
        onChange={(event) => onChange({ ...limit, amount: event.target.value })}
      />
      <label className="checkbox-row" htmlFor={`${id}-unlimited`}>
        <input
          id={`${id}-unlimited`}
          type="checkbox"
          checked={limit.unlimited}
          onChange={(event) => onChange({ ...limit, unlimited: event.target.checked })}
        />
        <span>
          <strong>{t("settings.plans.editor.unlimited")}</strong>
        </span>
      </label>
    </div>
  )
}
