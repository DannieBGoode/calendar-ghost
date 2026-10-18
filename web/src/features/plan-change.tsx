import { RefreshCw } from "lucide-react"
import { useEffect, useRef, useState, type KeyboardEvent } from "react"

import { Button } from "@/components/ui/button"
import { RadioRows, type RadioRowOption } from "@/components/ui/radio-rows"
import { scrollFullyIntoView } from "@/components/ui/keep-in-window"
import { Skeleton } from "@/components/ui/skeleton"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import type { PersonRow, PlanAssignments, PlanSummary, PlansOverview } from "@/lib/api"
import {
  changeMove,
  changeOptions,
  changeTitle,
  changedResult,
  choiceVerdict,
  chosenPlan,
  offered,
  sharedChoice,
  type ChangeOption,
  type ChoiceVerdict,
  type PlanPerson,
} from "@/lib/plan-change"
import { usePlanDryRun } from "@/lib/use-plan-assignment"
import { usePlanList, type PlanCommands } from "@/lib/use-plans"

/** What Save sends: a Plan's key, or null for the default, which they then follow, or for no Plan; and the Plan chosen, null for none. */
export type SaveChange = (plan: string | null, chosen: PlanSummary | null) => void

export type PlanChooserProps = {
  /** The chooser's own id, which its parts' ids start with. */
  id: string
  /** Its title: "Change plan" where the page already names them, otherwise who it is for. */
  title: string
  people: readonly PlanPerson[]
  overview: PlansOverview
  /** Its title's level: 3 on a page or in a popover, 5 under a person in a Plan's panel. */
  level: 3 | 5
  /** It opens in place in a card, rather than in a popover, so it scrolls fully into view as it opens. */
  inPlace?: boolean
  /** The change is on its way: every control keeps focus and waits. */
  pending: boolean
  /** Why the last change was refused, shown under the choice; null without one. */
  refusal: unknown
  /** A new choice was made, which puts a refusal away. */
  onChoose?: () => void
  /** Save with a choice that changes something. */
  onSave: SaveChange
  /** Cancel, Escape, or Save with what they have now: it closes, changing nothing. */
  onCancel: () => void
}

/**
 * The choice as it stands: what they all have now to start from, the option chosen, and what a dry
 * run says it would do. A Plan chosen that is no longer offered, as after a refusal, gives way to
 * what they have now. Nothing is asked of the server for what they have now.
 */
function useChoice({ people, overview, pending, onChoose }: PlanChooserProps) {
  const i18n = useI18n()
  const shared = sharedChoice(overview.plans, people)
  const [picked, setPicked] = useState<string | null>(shared)
  const [missing, setMissing] = useState(false)
  const choice = picked !== null && offered(overview.plans, picked) ? picked : shared
  const changes = choice !== null && choice !== shared
  const move = choice === null ? null : changeMove(overview.plans, choice)
  const dryRun = usePlanDryRun(move, changes ? people.map((person) => person.id) : [], pending)
  return {
    options: changeOptions(i18n, overview.plans, people),
    choice,
    changes,
    missing,
    verdict: changes ? choiceVerdict(i18n, people, dryRun.data) : null,
    ask: () => setMissing(true),
    choose: (next: string) => {
      setPicked(next)
      setMissing(false)
      onChoose?.()
    },
  }
}

/** Each option as a row, the one chosen with what the dry run says, in Attention Ochre while Plans are on. */
function optionRows(options: readonly ChangeOption[], choice: string | null, verdict: ChoiceVerdict | null, enabled: boolean): RadioRowOption<string>[] {
  return options.map((option) => ({
    value: option.value,
    title: option.title,
    summary: option.summary,
    badges: option.badges.map((badge) => ({ text: badge.text, variant: badge.kind === "default" ? "outline" : "neutral" })),
    note: option.value === choice && verdict ? { text: verdict.text, tone: verdict.over && enabled ? "attention" : undefined } : null,
  }))
}

/** Moves focus to the option chosen, or to the first when none is. */
function focusChoice(options: HTMLElement | null) {
  const radio = options?.querySelector<HTMLInputElement>("input[type='radio']:checked") ?? options?.querySelector<HTMLInputElement>("input[type='radio']")
  radio?.focus()
}

/** The ids an element's aria-describedby names, leaving out those not shown. */
function describedBy(...ids: (string | false)[]): string | undefined {
  return ids.filter(Boolean).join(" ") || undefined
}

/**
 * Change plan for one or more people: one compact row per Plan, the default first, where choosing
 * the default means they follow it, with a note that they then move with it. What they all have
 * now is chosen and marked Current; when they differ, each Plan counts who has it. Once another
 * choice is made, a dry run says under it which limits anyone would be over. Focus starts on the
 * option chosen. Save with what they have now closes it, sending nothing; with nothing chosen it
 * asks for a choice. While the change is on its way every control keeps focus and waits; a refusal
 * shows here. Escape or Cancel closes it.
 */
function PlanChooser(props: PlanChooserProps) {
  const { id, title, overview, level, inPlace, pending, refusal, onSave, onCancel } = props
  const { t } = useI18n()
  const state = useChoice(props)
  const chooser = useRef<HTMLDivElement>(null)
  const options = useRef<HTMLDivElement>(null)
  useEffect(() => {
    focusChoice(options.current)
  }, [])
  useEffect(() => {
    if (inPlace && chooser.current) scrollFullyIntoView(chooser.current)
  }, [inPlace])
  const Title = level === 3 ? "h3" : "h5"
  const hasDefault = overview.plans.some((plan) => plan.is_default)
  const cancel = () => !pending && onCancel()

  function save() {
    if (pending) return
    if (state.choice === null) {
      state.ask()
      focusChoice(options.current)
    } else if (!state.changes) {
      onCancel()
    } else {
      onSave(changeMove(overview.plans, state.choice), chosenPlan(overview.plans, state.choice))
    }
  }

  function escape(event: KeyboardEvent<HTMLElement>) {
    if (event.key !== "Escape") return
    // Whatever holds it stays open: the chooser closes itself, or waits while its change is on its way.
    event.preventDefault()
    cancel()
  }

  return (
    <div ref={chooser} id={id} className="plan-change" onKeyDown={escape}>
      <Title id={`${id}-title`}>{title}</Title>
      <div ref={options} className="plan-change-options">
        <RadioRows
          aria-labelledby={`${id}-title`}
          aria-describedby={describedBy(hasDefault && `${id}-note`, state.missing && `${id}-missing`)}
          aria-invalid={state.missing || undefined}
          options={optionRows(state.options, state.choice, state.verdict, overview.enabled)}
          value={state.choice}
          pending={pending}
          onValueChange={state.choose}
        />
      </div>
      {hasDefault && (
        <p id={`${id}-note`} className="plan-change-note">
          {t("people.plans.change.defaultNote")}
        </p>
      )}
      {state.missing && (
        <p id={`${id}-missing`} className="field-error" role="alert">
          {t("people.plans.change.chooseFirst")}
        </p>
      )}
      <ChangeRefusal refusal={refusal} />
      <div className="plan-change-actions">
        <Button type="button" size="sm" aria-disabled={pending || undefined} aria-busy={pending || undefined} onClick={save}>
          {t("people.plans.change.save")}
        </Button>
        <Button type="button" size="sm" variant="ghost" aria-disabled={pending || undefined} onClick={cancel}>
          {t("people.plans.change.cancel")}
        </Button>
      </div>
    </div>
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

/**
 * Change plan where the Plans are not at hand, on a person's page and in Everyone: the Plans are
 * read as it opens, with Try again when they cannot be, then the chooser.
 */
export function ChooserWithPlans(props: Omit<PlanChooserProps, "overview" | "level">) {
  const { t } = useI18n()
  const plans = usePlanList()
  if (plans.data) return <PlanChooser {...props} overview={plans.data} level={3} />
  if (plans.isPending) {
    return (
      <div role="status" aria-busy="true" aria-label={t("people.plans.change.loading")}>
        <h3 id={`${props.id}-title`} className="sr-only">
          {t("people.plans.change.loading")}
        </h3>
        <Skeleton className="h-40 w-full" />
      </div>
    )
  }
  return (
    <div className="plan-assign-error" role="alert">
      <h3 id={`${props.id}-title`}>{t("people.plans.change.loadError")}</h3>
      <Button type="button" variant="outline" size="sm" onClick={() => void plans.refetch()}>
        <RefreshCw aria-hidden="true" />
        {t("people.plans.tryAgain")}
      </Button>
    </div>
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
  const save: SaveChange = (plan, chosen) =>
    assign.mutate(
      { from, via: "change", moves: [{ plan, userIds: [person.id] }] },
      { onSuccess: ([answer]) => answer && onChanged(answer, changedResult(i18n, [person], chosen)) },
    )
  return (
    <PlanChooser
      id={`plan-change-${person.id}`}
      title={changeTitle(i18n, [person])}
      people={[person]}
      overview={overview}
      level={5}
      pending={assign.isPending}
      refusal={changeRefusal(assign, person.id)}
      onSave={save}
      onCancel={onCancel}
    />
  )
}
