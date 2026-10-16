import { useEffect, useRef, useState, type SyntheticEvent } from "react"

import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { NativeSelect } from "@/components/ui/native-select"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import type { Person, PersonPlan, PlanSummary } from "@/lib/api"
import { defaultPlanChoice, planChoiceAllows } from "@/lib/plans"
import type { PeopleCommands, PlanChoice } from "@/lib/use-people"
import { usePlanList } from "@/lib/use-plans"

/** The choice's value for the Default Plan; no Plan key is empty. */
const DEFAULT_PLAN = ""

/** The Plan a value of the choice gives: for the Default Plan, the Plan that is the default now. */
function chosenPlan(value: string, plans: readonly PlanSummary[]): PlanSummary | undefined {
  return plans.find((plan) => (value === DEFAULT_PLAN ? plan.is_default : plan.key === value))
}

/** The Plan a value of the choice gives, with the name its result says. */
function planChoice(value: string, plans: readonly PlanSummary[]): PlanChoice {
  const name = chosenPlan(value, plans)?.name
  return value === DEFAULT_PLAN ? { key: null, name: name ?? null } : { key: value, name: name ?? value }
}

/**
 * What the Plan chosen allows, under the choice. It is always present, so a screen reader
 * announces each new choice's limits; it says nothing until the Plans are read.
 */
function ChosenPlanAllows({ id, plans, value }: { id: string; plans: readonly PlanSummary[] | undefined; value: string }) {
  const i18n = useI18n()
  return (
    <p id={id} className="field-hint" aria-live="polite">
      {plans ? planChoiceAllows(i18n, chosenPlan(value, plans)) : null}
    </p>
  )
}

/** The ids an element's aria-describedby names, leaving out those not shown. */
function describedBy(...ids: (string | false | null | undefined)[]): string | undefined {
  return ids.filter(Boolean).join(" ") || undefined
}

/**
 * The choice as it stands: the Plans to choose from, the one chosen, and the refusal of the last
 * change, which takes focus as it arrives. While a change is on its way, every control keeps focus
 * but ignores input; choosing again puts a refusal away, and so does Cancel.
 */
function usePlanChoice(person: Person, current: PersonPlan | null, commands: PeopleCommands) {
  // People's Plans tab reads the same list under the same key.
  const plans = usePlanList()
  const listed = plans.data?.plans ?? []
  // Null until the administrator chooses, so the choice opens on their own Plan. A Plan no
  // longer listed is no choice, so it falls back to their own, then the default.
  const [chosen, setChosen] = useState<string | null>(null)
  const value =
    [chosen, current?.assigned?.key].find(
      (key) => key === DEFAULT_PLAN || listed.some((plan) => plan.key === key),
    ) ?? DEFAULT_PLAN
  const select = useRef<HTMLSelectElement>(null)
  const { busy } = commands
  const refused = commands.errorFor(person)
  useEffect(() => {
    if (refused) select.current?.focus()
  }, [refused])

  const choose = (next: string) => {
    if (busy) return
    if (refused) commands.command.reset()
    setChosen(next)
  }
  const save = () => {
    if (busy || !plans.data) return
    commands.send({ person, action: "plan", plan: planChoice(value, listed) })
  }
  const cancel = () => {
    if (busy) return
    commands.command.reset()
    commands.setChoosingPlan(null)
  }
  return { plans, listed, value, select, refused, choose, save, cancel }
}

/**
 * Which Plan limits this person, chosen inline beside them: one of the Plans by name, or the
 * Default Plan, named by the Plan that is the default now, which they then follow whenever it
 * changes. What the chosen Plan allows shows under the choice, rather than in its options, so
 * nothing is cut off on a narrow screen, and is announced as the choice changes. It opens on their
 * own Plan. Save sends the key, or null for the default;
 * the result names the Plan, and a refusal shows under the choice. The Plans are read again after
 * a refusal, so one removed meanwhile leaves the choice. Once the choice closes, by Cancel or a
 * saved Plan, focus returns to their actions, where Change plan opened it.
 */
export function PersonPlanChoice({
  person,
  name,
  current,
  commands,
}: {
  person: Person
  /** How People names them, as their actions menu's label does. */
  name: string
  current: PersonPlan | null
  commands: PeopleCommands
}) {
  const i18n = useI18n()
  const { t } = i18n
  const { plans, listed, value, select, refused, choose, save, cancel } = usePlanChoice(person, current, commands)
  useEffect(() => {
    select.current?.focus()
  }, [select])
  const actionsLabel = t("people.actions.label", { email: name })
  useEffect(
    () => () => {
      // Closing removed the focused control, unless the administrator already moved on.
      const active = document.activeElement
      if (active !== null && active !== document.body) return
      document.querySelector<HTMLElement>(`[aria-label=${JSON.stringify(actionsLabel)}]`)?.focus()
    },
    [actionsLabel],
  )
  const id = `person-plan-${person.id}`
  const waiting = commands.busy || undefined

  function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    save()
  }

  return (
    <form className="setting-form person-plan-choice" noValidate onSubmit={submit}>
      <div className="field-stack">
        <Label htmlFor={id}>{t("people.plan.label", { email: name })}</Label>
        <NativeSelect
          ref={select}
          id={id}
          value={value}
          aria-disabled={waiting}
          aria-invalid={refused ? true : undefined}
          aria-describedby={describedBy(Boolean(refused) && `${id}-error`, `${id}-allows`, `${id}-hint`)}
          onChange={(event) => choose(event.target.value)}
        >
          <option value={DEFAULT_PLAN}>{defaultPlanChoice(i18n, listed)}</option>
          {listed.map((plan) => (
            <option key={plan.key} value={plan.key}>
              {plan.name}
            </option>
          ))}
        </NativeSelect>
        <ChosenPlanAllows id={`${id}-allows`} plans={plans.data?.plans} value={value} />
        <p id={`${id}-hint`} className="field-hint">
          {t("people.plan.hint")}
        </p>
        {Boolean(refused) && (
          <p id={`${id}-error`} className="field-error" role="alert">
            {apiErrorMessage(i18n, refused)}
          </p>
        )}
      </div>
      {plans.error && (
        <p id={`${id}-load-error`} className="field-error" role="alert">
          {apiErrorMessage(i18n, plans.error)}
        </p>
      )}
      <div className="setting-form-actions">
        <Button
          type="submit"
          aria-disabled={waiting ?? (plans.data ? undefined : true)}
          aria-busy={waiting}
          aria-describedby={plans.error ? `${id}-load-error` : undefined}
        >
          {t("people.plan.save")}
        </Button>
        <Button type="button" variant="ghost" aria-disabled={waiting} onClick={cancel}>
          {t("people.plan.cancel")}
        </Button>
      </div>
    </form>
  )
}
