import * as React from "react"

import { cn } from "@/lib/utils"

import { Badge } from "./badge"
import { Radio } from "./radio"

type RadioCardOption<T extends string> = {
  value: T
  title: string
  description?: string
  /** A decorative mark before the title; the title still names the option. */
  icon?: React.ReactNode
  /** Why the option cannot be chosen, such as "Current"; it then stays visible, dimmed, beside its title. */
  unavailable?: string
}

type RadioCardsName = { "aria-label": string } | { "aria-labelledby": string }

type RadioCardsProps<T extends string> = RadioCardsName & {
  options: readonly RadioCardOption<T>[]
  /** The chosen option, or null before anything is chosen. */
  value: T | null
  onValueChange: (value: T) => void
  /** A command is on its way: every option keeps focus but ignores choices. */
  pending?: boolean
  "aria-describedby"?: string
  className?: string
}

/**
 * A choice whose options each need a sentence, as bordered cards in one native radio group: Tab
 * stops once, the arrow keys move the choice, and pressing anywhere on a card chooses it. Each
 * radio is named by its title and described by its sentence; the chosen card is outlined in the
 * palette's lantern color.
 */
function RadioCards<T extends string>({
  options,
  value,
  onValueChange,
  pending = false,
  className,
  ...group
}: RadioCardsProps<T>) {
  const id = React.useId()
  return (
    <div role="radiogroup" className={cn("grid gap-2", className)} {...group}>
      {options.map((option) => (
        <RadioCard
          key={option.value}
          id={`${id}-${option.value}`}
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

function RadioCard<T extends string>({
  id,
  name,
  option,
  checked,
  pending,
  onChoose,
}: {
  id: string
  name: string
  option: RadioCardOption<T>
  checked: boolean
  pending: boolean
  onChoose: () => void
}) {
  const descriptionId = option.description ? `${id}-description` : undefined
  return (
    <div className="relative grid grid-cols-[auto_minmax(0,1fr)] items-start gap-x-3 gap-y-1 rounded-[0.625rem] border border-border bg-background px-3.5 py-3 transition-[border-color,box-shadow] duration-200 has-checked:border-primary has-checked:shadow-[inset_0_0_0_1px_var(--primary)] has-disabled:opacity-60 has-[:enabled:not(:checked)]:hover:border-input">
      <Radio
        id={id}
        name={name}
        value={option.value}
        checked={checked}
        disabled={Boolean(option.unavailable)}
        aria-disabled={pending || undefined}
        aria-describedby={descriptionId}
        className="mt-[0.1875rem] size-4 checked:border-[5px]"
        onChange={onChoose}
      />
      <label
        htmlFor={id}
        className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-[0.9375rem] font-semibold leading-snug text-foreground after:absolute after:inset-0 after:rounded-[0.625rem] after:content-[''] peer-focus-visible:after:ring-[3px] peer-focus-visible:after:ring-ring/90 peer-enabled:cursor-pointer peer-disabled:cursor-not-allowed peer-aria-disabled:cursor-not-allowed [&>svg]:size-4 [&>svg]:shrink-0"
      >
        {option.icon}
        {option.title}
        {/* A space, so the reason reads as its own word in the radio's name ("Free Current"). */}
        {option.unavailable && (
          <>
            {" "}
            <Badge variant="neutral">{option.unavailable}</Badge>
          </>
        )}
      </label>
      {option.description && (
        <p id={descriptionId} className="col-start-2 text-[0.8125rem] leading-normal text-muted-foreground">
          {option.description}
        </p>
      )}
    </div>
  )
}

export { RadioCards }
