import { CheckCircle2, TriangleAlert } from "lucide-react"
import { useEffect, useRef, useState, type KeyboardEvent } from "react"

import { Button } from "@/components/ui/button"
import { RadioCards } from "@/components/ui/radio-cards"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import type { PersonRow, PlanAssignments, PlanSummary, PlansOverview } from "@/lib/api"
import {
  FOLLOW_DEFAULT,
  changeChoices,
  changeConfirm,
  changeReason,
  changeResult,
  changeTitle,
  changedResult,
  chosenPlan,
  heldNow,
  type ChangeOutcome,
  type PlanPerson,
} from "@/lib/plan-assignment"
import { usePlanDryRun } from "@/lib/use-plan-assignment"
import type { PlanCommands } from "@/lib/use-plans"

/** Where the chooser sends a change: a Plan by its key, or the Default Plan with null, and that Plan. */
export type ConfirmChange = (plan: string | null, chosen: PlanSummary | undefined) => void

export type PlanChooserProps = {
  /** The chooser's own id, which its parts' ids start with. */
  id: string
  people: readonly PlanPerson[]
  overview: PlansOverview
  /** Its title's level: 3 in a popover on a page, 5 under a person in a Plan's panel. */
  level: 3 | 5
  /** The change is on its way: every control keeps focus and waits. */
  pending: boolean
  /** Why the last change was refused, shown under the chooser; null without one. */
  refusal: unknown
  /** A new choice was made, which puts a refusal away. */
  onChoose?: () => void
  onConfirm: ConfirmChange
  onCancel: () => void
}

/**
 * The choice as it stands: the Plan chosen, or the default with FOLLOW_DEFAULT, nothing until then
 * or once the Plan chosen is no longer offered; and what a dry run says it would do for them.
 */
function useChoice({ people, overview, pending, onChoose }: PlanChooserProps) {
  const i18n = useI18n()
  const [picked, setPicked] = useState<string | null>(null)
  const options = changeChoices(i18n, overview.plans, people)
  const choice = options.some((option) => option.value === picked && !option.unavailable) ? picked : null
  const plan = choice === null ? undefined : chosenPlan(overview.plans, choice)
  const follows = choice === FOLLOW_DEFAULT
  const dryRun = usePlanDryRun(follows ? null : choice, choice === null ? [] : people.map((person) => person.id), pending)
  const outcome = changeResult(i18n, people, { plan, follows }, dryRun.data)
  return {
    options,
    choice,
    plan,
    outcome,
    choose: (next: string) => {
      setPicked(next)
      onChoose?.()
    },
  }
}

/**
 * Change plan for one or more people: what they have now, then "Follow the default plan" and each
 * Plan with what it allows, what every one of them has marked "Current". Once a choice is made, a
 * dry run says before anyone confirms who moves where and who would have more than it allows. Its
 * title takes focus as it opens. While the change is on its way every control keeps focus and
 * waits; a refusal shows here. Escape or Cancel closes it.
 */
export function PlanChooser(props: PlanChooserProps) {
  const { id, people, overview, level, pending, refusal, onConfirm, onCancel } = props
  const i18n = useI18n()
  const { options, choice, plan, outcome, choose } = useChoice(props)
  const heading = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    heading.current?.focus()
  }, [])
  const Title = level === 3 ? "h3" : "h5"
  const cancel = () => !pending && onCancel()
  const attention = outcome.over && overview.enabled

  function escape(event: KeyboardEvent<HTMLElement>) {
    if (event.key !== "Escape") return
    // Whatever holds it stays open: the chooser closes itself, or waits while its change is on its way.
    event.preventDefault()
    cancel()
  }

  return (
    <section id={id} className="plan-change" aria-labelledby={`${id}-title`} onKeyDown={escape}>
      <Title id={`${id}-title`} ref={heading} tabIndex={-1}>
        {changeTitle(i18n, people)}
      </Title>
      <p className="plan-change-held">{heldNow(i18n, people)}</p>
      <RadioCards
        aria-labelledby={`${id}-title`}
        aria-describedby={`${id}-result`}
        options={options}
        value={choice}
        pending={pending}
        onValueChange={choose}
      />
      <ChangeOutcomeLine id={`${id}-result`} outcome={outcome} attention={attention} />
      <div className="plan-change-actions">
        <Button
          type="button"
          size="sm"
          aria-disabled={choice === null || pending || undefined}
          aria-busy={pending || undefined}
          aria-describedby={choice === null ? `${id}-reason` : undefined}
          onClick={() => choice !== null && !pending && onConfirm(choice === FOLLOW_DEFAULT ? null : choice, plan)}
        >
          {changeConfirm(i18n, people, choice, plan)}
        </Button>
        <Button type="button" size="sm" variant="ghost" aria-disabled={pending || undefined} onClick={cancel}>
          {i18n.t("people.plans.change.cancel")}
        </Button>
      </div>
      {choice === null && (
        <p id={`${id}-reason`} className="field-hint">
          {changeReason(i18n, people)}
        </p>
      )}
      <ChangeRefusal refusal={refusal} />
    </section>
  )
}

/**
 * What the dry run found, announced as it arrives: an icon beside the words, the attention icon
 * when someone would be over, in Attention Ochre while Plans are on.
 */
function ChangeOutcomeLine({ id, outcome, attention }: { id: string; outcome: ChangeOutcome; attention: boolean }) {
  return (
    <p id={id} className="plan-change-result" role="status" data-tone={attention ? "attention" : undefined}>
      {outcome.text && (outcome.over ? <TriangleAlert aria-hidden="true" /> : <CheckCircle2 aria-hidden="true" />)}
      {outcome.text}
    </p>
  )
}

function ChangeRefusal({ refusal }: { refusal: unknown }) {
  const i18n = useI18n()
  if (!refusal) return null
  return (
    <p className="field-error" role="alert">
      {apiErrorMessage(i18n, refusal)}
    </p>
  )
}

type Assign = PlanCommands["assign"]

/** Why the last change for this person was refused, to show under their chooser. */
function changeRefusal(assign: Assign, personId: string): Error | null {
  if (!assign.error || assign.variables.via !== "change") return null
  return assign.variables.moves[0]?.userIds[0] === personId ? assign.error : null
}

/**
 * Change plan for one person who has the Plan `from`, under their row in its panel. The change is
 * one command, whose refusal shows here; once made, `onChanged` hears what it did and its words.
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
  const confirm: ConfirmChange = (plan, chosen) =>
    assign.mutate(
      { from, via: "change", moves: [{ plan, userIds: [person.id] }] },
      { onSuccess: ([answer]) => answer && onChanged(answer, changedResult(i18n, [person], plan === null ? null : chosen)) },
    )
  return (
    <PlanChooser
      id={`plan-change-${person.id}`}
      people={[person]}
      overview={overview}
      level={5}
      pending={assign.isPending}
      refusal={changeRefusal(assign, person.id)}
      onConfirm={confirm}
      onCancel={onCancel}
    />
  )
}
