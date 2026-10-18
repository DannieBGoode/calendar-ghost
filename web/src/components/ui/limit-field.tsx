import { Minus, Plus } from "lucide-react"
import * as React from "react"

import { Radio } from "./radio"

/** "none" is offered only where zero is a real choice, as for Integration Tokens. */
type LimitChoice = "none" | "upTo" | "noLimit"

/** The option chosen, and the number typed, which is kept while another option is chosen. */
type LimitValue = { choice: LimitChoice; amount: string }

type LimitFieldLabels = {
  noLimit: string
  upTo: string
  /** Offers None first and No limit last, as `None | Up to [n] | No limit`. */
  none?: string | undefined
  /** The number's buttons, for a pointer; the arrow keys step it too. */
  fewer: string
  more: string
}

type NumberProps = Omit<
  React.ComponentProps<"input">,
  "type" | "value" | "onChange" | "role" | "inputMode" | "readOnly" | "tabIndex" | "onKeyDown" | "onFocus" | "ref"
> & { "data-field"?: string }

type LimitFieldProps = {
  legend: string
  /** One line on what counts, under the legend and above the control. */
  hint?: string | undefined
  labels: LimitFieldLabels
  /** The word after the number, such as "rules", already in the number's plural. */
  unit?: string | undefined
  min: number
  max: number
  value: LimitValue
  onChange: (value: LimitValue) => void
  /** A save is on its way: every control keeps focus but ignores changes. */
  pending?: boolean | undefined
  /** The number field's own attributes, such as the id a refusal focuses and the ids that describe it. */
  inputProps?: NumberProps | undefined
  /** What follows the control, such as a warning or a refusal. */
  children?: React.ReactNode
}

type Bounds = { min: number; max: number }

/** Steps an amount by `delta`; an empty amount starts at the least. */
const by =
  (delta: number) =>
  (current: number | null, { min }: Bounds): number =>
    current === null ? min : current + delta

/** The spin button keys, as WAI-ARIA describes them. */
const KEY_STEPS: Partial<Record<string, (current: number | null, bounds: Bounds) => number>> = {
  ArrowUp: by(1),
  ArrowDown: by(-1),
  PageUp: by(10),
  PageDown: by(-10),
  Home: (_current, { min }) => min,
  End: (_current, { max }) => max,
}

/** The whole number an amount holds, or null while it holds none. */
function wholeNumber(amount: string): number | null {
  return /^\d+$/.test(amount) ? Number(amount) : null
}

/**
 * A limit that may be unlimited, as one segmented control: `No limit | Up to [- 3 +] rules`, or
 * `None | Up to [- 2 +] | No limit`. Its options are one native radio group, so Tab stops once
 * and the arrow keys move the choice. The number is a text field with a numeric keyboard, so a
 * scroll wheel never changes it, and a WAI-ARIA spin button: the arrow keys step it by one, Page
 * Up and Page Down by ten, and Home and End go to its bounds. While another option is chosen, the
 * number stays visible, dimmed, so choosing Up to again keeps it; it is out of the tab sequence
 * then, and pointing at it chooses Up to. Where the field is narrow, as on a phone, the options
 * stack as a list, each a full-width row; wider, an option that wraps to its own line fills it.
 */
function LimitField({
  legend,
  hint,
  labels,
  unit,
  min,
  max,
  value,
  onChange,
  pending = false,
  inputProps,
  children,
}: LimitFieldProps) {
  const id = React.useId()
  const legendId = `${id}-legend`
  const hintId = `${id}-hint`
  const change = (next: Partial<LimitValue>) => {
    if (!pending) onChange({ ...value, ...next })
  }
  const segment = (choice: "none" | "noLimit", label: string) => (
    <Segment id={`${id}-${choice}`} name={id} label={label} checked={value.choice === choice} pending={pending} onChoose={() => change({ choice })} />
  )
  return (
    <fieldset className="@container m-0 min-w-0 border-0 p-0" aria-describedby={hint ? hintId : undefined}>
      <legend id={legendId} className="p-0 text-sm font-semibold leading-snug text-foreground">
        {legend}
      </legend>
      {hint && (
        <p id={hintId} className="mt-0.5 text-[0.8125rem] leading-normal text-muted-foreground">
          {hint}
        </p>
      )}
      <div className="mt-2 flex w-fit max-w-full flex-wrap items-stretch gap-[3px] rounded-[0.625rem] border border-input bg-background p-[3px] @max-[22rem]:w-full @max-[22rem]:flex-col">
        {labels.none === undefined ? segment("noLimit", labels.noLimit) : segment("none", labels.none)}
        <Segment
          id={`${id}-upTo`}
          name={id}
          label={labels.upTo}
          checked={value.choice === "upTo"}
          pending={pending}
          onChoose={() => change({ choice: "upTo" })}
        >
          <Stepper
            amount={value.amount}
            active={value.choice === "upTo"}
            bounds={{ min, max }}
            legendId={legendId}
            labels={labels}
            pending={pending}
            inputProps={{ ...inputProps, id: inputProps?.id ?? `${id}-amount` }}
            onAmount={(amount) => change({ choice: "upTo", amount })}
          />
          {unit && <span className="pr-1 whitespace-nowrap">{unit}</span>}
        </Segment>
        {labels.none !== undefined && segment("noLimit", labels.noLimit)}
      </div>
      {children}
    </fieldset>
  )
}

/**
 * One option of the segmented control; a label stretched over it makes the whole option choose it.
 * It grows to fill a line it wraps to. Up to wraps its number and unit onto a second line when the
 * field is too narrow for one.
 */
function Segment({
  id,
  name,
  label,
  checked,
  pending,
  onChoose,
  children,
}: {
  id: string
  name: string
  label: string
  checked: boolean
  pending: boolean
  onChoose: () => void
  children?: React.ReactNode
}) {
  return (
    <span className="relative inline-flex min-h-[2.125rem] flex-auto flex-wrap items-center gap-x-2 gap-y-1 rounded-[0.4375rem] border border-transparent px-3 text-sm font-semibold text-muted-foreground transition-colors duration-200 has-checked:border-border has-checked:bg-muted has-checked:text-foreground has-checked:shadow-[0_1px_0_color-mix(in_oklch,var(--foreground)_6%,transparent)] pointer-coarse:min-h-11">
      <Radio id={id} name={name} checked={checked} aria-disabled={pending || undefined} onChange={onChoose} />
      <label
        htmlFor={id}
        className="whitespace-nowrap after:absolute after:inset-0 after:rounded-[0.4375rem] peer-focus-visible:after:ring-[3px] peer-focus-visible:after:ring-ring/90 peer-enabled:cursor-pointer peer-aria-disabled:cursor-not-allowed"
      >
        {label}
      </label>
      {children}
    </span>
  )
}

/** The number, between Fewer and More, above the stretched label so pointing at it never chooses through it. */
function Stepper({
  amount,
  active,
  bounds,
  legendId,
  labels,
  pending,
  inputProps,
  onAmount,
}: {
  amount: string
  active: boolean
  bounds: Bounds
  legendId: string
  labels: LimitFieldLabels
  pending: boolean
  inputProps: NumberProps & { id: string }
  onAmount: (amount: string) => void
}) {
  const step = (move: (current: number | null, bounds: Bounds) => number) => {
    const next = move(wholeNumber(amount), bounds)
    onAmount(String(Math.min(Math.max(next, bounds.min), bounds.max)))
  }
  const current = wholeNumber(amount)
  return (
    <span
      data-stepper=""
      data-inactive={active ? undefined : ""}
      className="relative z-[1] inline-flex items-center rounded-[0.4375rem] border border-input bg-background transition-[opacity,border-color,box-shadow] duration-200 has-focus-visible:border-primary has-focus-visible:ring-[3px] has-focus-visible:ring-ring/90 data-inactive:opacity-45"
    >
      <StepButton label={labels.fewer} controls={inputProps.id} pending={pending} onPress={() => step(by(-1))}>
        <Minus />
      </StepButton>
      <input
        {...inputProps}
        type="text"
        inputMode="numeric"
        role="spinbutton"
        autoComplete="off"
        maxLength={String(bounds.max).length}
        aria-labelledby={legendId}
        aria-valuemin={bounds.min}
        aria-valuemax={bounds.max}
        aria-valuenow={current ?? undefined}
        aria-disabled={pending || undefined}
        readOnly={pending}
        tabIndex={active ? 0 : -1}
        value={amount}
        className="h-7.5 w-14 min-w-0 bg-transparent px-1 text-center text-sm font-semibold tabular-nums text-foreground outline-hidden pointer-coarse:h-11"
        onChange={(event) => onAmount(event.target.value.replace(/\D/g, ""))}
        onFocus={() => {
          if (!active) onAmount(amount)
        }}
        onKeyDown={(event) => {
          const move = KEY_STEPS[event.key]
          if (!move) return
          event.preventDefault()
          step(move)
        }}
      />
      <StepButton label={labels.more} controls={inputProps.id} pending={pending} onPress={() => step(by(1))}>
        <Plus />
      </StepButton>
    </span>
  )
}

/**
 * Fewer or More, for a pointer only, as a spin button's buttons are: the arrow keys do the same
 * from the number, so they stay out of the tab sequence, and pressing one leaves focus where it was.
 */
function StepButton({
  label,
  controls,
  pending,
  onPress,
  children,
}: {
  label: string
  controls: string
  pending: boolean
  onPress: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      tabIndex={-1}
      aria-label={label}
      aria-controls={controls}
      aria-disabled={pending || undefined}
      className="inline-flex size-7.5 shrink-0 items-center justify-center rounded-[0.375rem] text-muted-foreground transition-colors duration-200 hover:text-foreground aria-disabled:cursor-not-allowed pointer-coarse:size-11 [&>svg]:size-3.5"
      onMouseDown={(event) => event.preventDefault()}
      onClick={onPress}
    >
      {children}
    </button>
  )
}

export { LimitField, type LimitValue }
