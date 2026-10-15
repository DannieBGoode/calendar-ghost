import { useQuery } from "@tanstack/react-query"
import { useEffect, useRef, useState, type SyntheticEvent } from "react"

import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { NativeSelect } from "@/components/ui/native-select"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import { api, type Person, type PersonPlan } from "@/lib/api"
import { personName } from "@/lib/people"
import type { PeopleCommands } from "@/lib/use-people"
import { PLANS_QUERY } from "@/lib/use-plans"

/** The choice's value for the Default Plan; no Plan key is empty. */
const DEFAULT_PLAN = ""

/**
 * Which Plan limits this person, chosen inline beside them: one of the Plans, or the Default
 * Plan, which they then follow whenever it changes. It opens on their own Plan. Save sends the
 * key, or null for the default; the server's refusal shows beside them, as for any command.
 */
export function PersonPlanChoice({
  person,
  current,
  commands,
}: {
  person: Person
  current: PersonPlan | null
  commands: PeopleCommands
}) {
  const i18n = useI18n()
  const { t } = i18n
  // The Administration Plans section reads the same list under the same key.
  const plans = useQuery({ queryKey: PLANS_QUERY, queryFn: api.plans })
  // Null until the administrator chooses, so the choice opens on their own Plan.
  const [chosen, setChosen] = useState<string | null>(null)
  const value = chosen ?? current?.assigned?.key ?? DEFAULT_PLAN
  const select = useRef<HTMLSelectElement>(null)
  useEffect(() => {
    select.current?.focus()
  }, [])
  const id = `person-plan-${person.id}`

  function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    commands.send({ person, action: "plan", plan: value || null })
  }

  return (
    <form className="setting-form person-plan-choice" onSubmit={submit}>
      <div className="field-stack">
        <Label htmlFor={id}>{t("people.plan.label", { email: personName(i18n, person) })}</Label>
        <NativeSelect ref={select} id={id} value={value} onChange={(event) => setChosen(event.target.value)}>
          <option value={DEFAULT_PLAN}>{t("people.plan.default")}</option>
          {(plans.data?.plans ?? []).map((plan) => (
            <option key={plan.key} value={plan.key}>
              {plan.name}
            </option>
          ))}
        </NativeSelect>
      </div>
      {plans.error && (
        <p className="field-error" role="alert">
          {apiErrorMessage(i18n, plans.error)}
        </p>
      )}
      <div className="setting-form-actions">
        <Button type="submit" disabled={commands.busy || !plans.data}>
          {t("people.plan.save")}
        </Button>
        <Button type="button" variant="ghost" onClick={() => commands.setChoosingPlan(null)}>
          {t("people.plan.cancel")}
        </Button>
      </div>
    </form>
  )
}
