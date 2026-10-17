import { useEffect, useRef, useState, type KeyboardEvent } from "react"

import { Button } from "@/components/ui/button"
import { RadioCards } from "@/components/ui/radio-cards"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import type { PersonRow, PlanAssignments, PlansOverview } from "@/lib/api"
import { personName } from "@/lib/people"
import { FOLLOW_DEFAULT, changeChoices, changeConfirm, changeResult, changedResult, chosenPlan } from "@/lib/plan-assignment"
import { usePlanDryRun } from "@/lib/use-plan-assignment"
import type { PlanCommands } from "@/lib/use-plans"

type Assign = PlanCommands["assign"]

/** Why the last change for this person was refused, to show under their chooser. */
function changeRefusal(assign: Assign, personId: string): Error | null {
  if (!assign.error || assign.variables.via !== "change") return null
  return assign.variables.moves[0]?.userIds[0] === personId ? assign.error : null
}

/**
 * The choice as it stands: the Plan chosen, or the default with FOLLOW_DEFAULT, nothing until
 * then; what a dry run says it would do for them; and the change, sent once confirmed.
 */
function useChange(person: PersonRow, from: string, overview: PlansOverview, assign: Assign) {
  const i18n = useI18n()
  const [choice, setChoice] = useState<string | null>(null)
  const pending = assign.isPending
  const plan = choice === null ? undefined : chosenPlan(overview.plans, choice)
  const target = choice === FOLLOW_DEFAULT ? null : choice
  const dryRun = usePlanDryRun(target, choice === null ? [] : [person.id], pending)
  const over = dryRun.data?.people[0]?.over
  return {
    choice,
    plan,
    pending,
    result: changeResult(i18n, person, plan, over),
    attention: overview.enabled && (over?.length ?? 0) > 0,
    choose: (next: string) => setChoice(next),
    confirm: (onChanged: (answer: PlanAssignments, message: string) => void) => {
      if (choice === null || pending) return
      assign.mutate(
        { from, via: "change", moves: [{ plan: target, userIds: [person.id] }] },
        { onSuccess: ([answer]) => answer && onChanged(answer, changedResult(i18n, person, target === null ? null : plan)) },
      )
    },
  }
}

/**
 * Change plan for one person who has the Plan `from`, under their row in its panel: "Follow the
 * default plan", then each Plan with what it allows, what they have now marked "Current". Once a
 * choice is made, a dry run says before anyone confirms whether they would have more than it
 * allows. The change is one command; while it is on its way every control keeps focus and waits,
 * and a refusal shows here. Escape or Cancel closes it.
 */
export function PlanChange({
  person,
  from,
  overview,
  assign,
  onChanged,
  onCancel,
}: {
  person: PersonRow
  /** The Plan whose panel this is, by key. */
  from: string
  overview: PlansOverview
  assign: Assign
  /** The change is made: what it did, and the words its result says. */
  onChanged: (answer: PlanAssignments, message: string) => void
  onCancel: () => void
}) {
  const i18n = useI18n()
  const change = useChange(person, from, overview, assign)
  const heading = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    heading.current?.focus()
  }, [])
  const refused = changeRefusal(assign, person.id)
  const name = personName(i18n, person)
  const base = `plan-change-${person.id}`
  const cancel = () => !change.pending && onCancel()

  function escape(event: KeyboardEvent<HTMLElement>) {
    if (event.key !== "Escape") return
    // The panel around it stays open.
    event.preventDefault()
    cancel()
  }

  return (
    <section id={base} className="plan-change" aria-labelledby={`${base}-title`} onKeyDown={escape}>
      <h5 id={`${base}-title`} ref={heading} tabIndex={-1}>
        {i18n.t("people.plans.change.title", { person: name })}
      </h5>
      <RadioCards
        aria-labelledby={`${base}-title`}
        aria-describedby={`${base}-result`}
        options={changeChoices(i18n, overview.plans, person)}
        value={change.choice}
        pending={change.pending}
        onValueChange={change.choose}
      />
      <p id={`${base}-result`} className="plan-change-result" role="status" data-tone={change.attention ? "attention" : undefined}>
        {change.result}
      </p>
      <div className="plan-change-actions">
        <Button
          type="button"
          size="sm"
          aria-disabled={change.choice === null || change.pending || undefined}
          aria-busy={change.pending || undefined}
          aria-describedby={change.choice === null ? `${base}-reason` : undefined}
          onClick={() => change.confirm(onChanged)}
        >
          {changeConfirm(i18n, person, change.choice, change.plan)}
        </Button>
        <Button type="button" size="sm" variant="ghost" aria-disabled={change.pending || undefined} onClick={cancel}>
          {i18n.t("people.plans.change.cancel")}
        </Button>
      </div>
      {change.choice === null && (
        <p id={`${base}-reason`} className="field-hint">
          {i18n.t("people.plans.change.chooseReason", { person: name })}
        </p>
      )}
      {refused && (
        <p className="field-error" role="alert">
          {apiErrorMessage(i18n, refused)}
        </p>
      )}
    </section>
  )
}
