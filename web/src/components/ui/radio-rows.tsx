import { TriangleAlert } from "lucide-react"
import * as React from "react"

import { cn } from "@/lib/utils"

import { Badge } from "./badge"
import { Radio } from "./radio"

/** One option: its title, a short summary beside it, badges read with its title, and what choosing it would do. */
type RadioRowOption<T extends string> = {
  value: T
  title: string
  /** A few words beside the title, such as what a Plan allows: "1 rule, 1 account, no tokens". */
  summary?: string
  /** Read with the title as the radio's name: "Default" in outline, "Current" neutral. */
  badges?: readonly { text: string; variant?: "outline" | "neutral" }[]
  /** What choosing it would do, under it; "attention" in Attention Ochre with its icon. */
  note?: { text: string; tone?: "attention" | undefined } | null
}

type RadioRowsName = { "aria-label": string } | { "aria-labelledby": string }

type RadioRowsProps<T extends string> = RadioRowsName & {
  options: readonly RadioRowOption<T>[]
  /** The chosen option, or null before anything is chosen. */
  value: T | null
  onValueChange: (value: T) => void
  /** A command is on its way: every option keeps focus but ignores choices. */
  pending?: boolean
  "aria-describedby"?: string | undefined
  /** No choice was made, or it was refused, as a form's refusal names it. */
  "aria-invalid"?: boolean | undefined
  className?: string
}

/**
 * A choice among things a name and a few words tell apart, such as Plans: one compact row per
 * option in one native radio group. Tab stops once, the arrow keys move the choice, and pressing
 * anywhere on a row chooses it. Each radio is named by its title and badges and described by its
 * summary, and the chosen row is tinted. Under each row, a line says what choosing it would do; it
 * is a live region from the start, so a screen reader announces it as it fills.
 */
function RadioRows<T extends string>({
  options,
  value,
  onValueChange,
  pending = false,
  className,
  ...group
}: RadioRowsProps<T>) {
  const id = React.useId()
  return (
    <div role="radiogroup" className={cn("grid gap-0.5", className)} {...group}>
      {options.map((option, index) => (
        <RadioRow
          key={option.value}
          id={`${id}-${index}`}
          name={id}
          option={option}
          checked={option.value === value}
          pending={pending}
          onChoose={() => {
            if (!pending) onValueChange(option.value)
          }}
        />
      ))}
    </div>
  )
}

function RadioRow<T extends string>({
  id,
  name,
  option,
  checked,
  pending,
  onChoose,
}: {
  id: string
  name: string
  option: RadioRowOption<T>
  checked: boolean
  pending: boolean
  onChoose: () => void
}) {
  const summaryId = option.summary ? `${id}-summary` : undefined
  const noteId = option.note ? `${id}-note` : undefined
  return (
    <div className="relative grid cursor-pointer grid-cols-[auto_minmax(0,1fr)] items-start gap-x-3 rounded-lg px-3 py-2 transition-colors duration-150 has-checked:bg-(--primary-soft) has-[input:not(:checked):not([aria-disabled])]:hover:bg-muted has-[input:focus-visible]:ring-[3px] has-[input:focus-visible]:ring-ring/90 has-[input[aria-disabled]]:cursor-not-allowed motion-reduce:transition-none pointer-coarse:py-2.5">
      <Radio
        id={id}
        name={name}
        value={option.value}
        checked={checked}
        aria-disabled={pending || undefined}
        aria-describedby={[summaryId, noteId].filter(Boolean).join(" ") || undefined}
        className="mt-[0.3125rem]"
        onChange={onChoose}
      />
      <div className="flex min-w-0 flex-wrap items-baseline gap-x-2.5 gap-y-0.5">
        <label
          htmlFor={id}
          className="inline-flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-1 text-[0.9375rem] leading-snug font-semibold text-foreground after:absolute after:inset-0 after:rounded-lg after:content-['']"
        >
          {option.title}
          <RowBadges badges={option.badges ?? []} />
        </label>
        {option.summary && (
          <span id={summaryId} className="text-[0.8125rem] leading-snug text-muted-foreground">
            {option.summary}
          </span>
        )}
      </div>
      <RowNote id={`${id}-note`} note={option.note ?? null} />
    </div>
  )
}

/** The badges after a row's title, each after a space, so it reads as its own word in the radio's name ("Free Current"). */
function RowBadges({ badges }: { badges: NonNullable<RadioRowOption<string>["badges"]> }) {
  return badges.map((badge) => (
    <React.Fragment key={badge.text}>
      {" "}
      <Badge variant={badge.variant ?? "neutral"} className="px-2 py-0.5 text-[0.6875rem]">
        {badge.text}
      </Badge>
    </React.Fragment>
  ))
}

/**
 * What choosing a row would do, under it: a live region from the start, empty until there is
 * something to say, in Attention Ochre with its icon for "attention".
 */
function RowNote({ id, note }: { id: string; note: RadioRowOption<string>["note"] }) {
  const attention = note?.tone === "attention"
  return (
    <p
      id={id}
      role="status"
      data-tone={attention ? "attention" : undefined}
      className="col-start-2 flex items-start gap-1.5 text-[0.8125rem] leading-snug text-muted-foreground data-[tone=attention]:text-warning-foreground [&:not(:empty)]:mt-1 [&>svg]:mt-[0.1875rem] [&>svg]:size-3.5 [&>svg]:shrink-0"
    >
      {attention && <TriangleAlert aria-hidden="true" />}
      {note?.text}
    </p>
  )
}

export { RadioRows, type RadioRowOption }
