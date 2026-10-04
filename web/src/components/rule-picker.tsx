import { ArrowRight, Check, ChevronDown, X } from "lucide-react"
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react"

import { AccountAvatar } from "@/components/account-avatar"
import type { ConnectedAccount } from "@/lib/api"
import {
  isTypeaheadKey,
  listCommand,
  movedIndex,
  openingIndex,
  typeaheadIndex,
  type ListCommand,
} from "@/lib/rule-picker"
import { cn } from "@/lib/utils"

export type RulePickerEndpoint = {
  calendar: string
  accountId: string
  account: ConnectedAccount | undefined
}

export type RulePickerOption = {
  value: string
  /** Spoken and matched by typeahead, such as "Personal to Work". */
  name: string
  source?: RulePickerEndpoint
  destination?: RulePickerEndpoint
  removed?: boolean
}

/**
 * A select-only combobox (WAI-ARIA APG) whose options show each rule's calendars with their
 * account avatars. Focus stays on the combobox; the active option is named by
 * aria-activedescendant.
 */
export function RulePicker({
  id: comboId,
  labelId,
  value,
  options,
  showAccounts,
  clearValue,
  clearLabel = "Clear",
  onChange,
}: {
  id: string
  labelId: string
  value: string
  options: RulePickerOption[]
  /** Adds account emails where calendar names alone would not tell rules apart. */
  showAccounts: boolean
  /** The unfiltered value. When set and another option is chosen, a clear button appears. */
  clearValue?: string
  clearLabel?: string
  onChange: (value: string) => void
}) {
  const id = useId()
  const listId = `${id}-list`
  const listRef = useRef<HTMLDivElement>(null)
  const comboRef = useRef<HTMLDivElement>(null)
  const typed = useRef({ text: "", at: 0 })
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const selectedIndex = options.findIndex((option) => option.value === value)
  const selected = options[selectedIndex] ?? options[0]

  useEffect(() => {
    if (!open) return
    listRef.current?.querySelector(`[data-index="${active}"]`)?.scrollIntoView({ block: "nearest" })
  }, [open, active])

  function show(index: number) {
    setActive(index)
    setOpen(true)
  }

  function choose(index: number) {
    setOpen(false)
    const option = options[index]
    if (option && option.value !== value) onChange(option.value)
  }

  function findTyped(key: string, from: number): number {
    const now = Date.now()
    typed.current = { text: now - typed.current.at < 600 ? typed.current.text + key : key, at: now }
    return typeaheadIndex(
      options.map((option) => option.name),
      typed.current.text,
      from,
    )
  }

  const clearable = canClear(value, clearValue, selectedIndex)

  function clear() {
    setOpen(false)
    if (clearValue !== undefined) onChange(clearValue)
    comboRef.current?.focus()
  }

  function handleClosedKey(event: KeyboardEvent<HTMLDivElement>, printable: boolean) {
    if (clearable && (event.key === "Delete" || event.key === "Backspace")) {
      event.preventDefault()
      clear()
      return
    }
    const index = printable ? findTyped(event.key, selectedIndex) : openingIndex(event.key, event.altKey, selectedIndex, options.length)
    if (index === null || index < 0) return
    event.preventDefault()
    show(index)
  }

  function runListCommand(event: KeyboardEvent<HTMLDivElement>, command: ListCommand) {
    // Tab keeps its default so focus still moves on.
    if (command !== "chooseAndLeave") event.preventDefault()
    if (command === "close") setOpen(false)
    else choose(active)
  }

  function moveWithKey(event: KeyboardEvent<HTMLDivElement>, printable: boolean) {
    const moved = printable ? findTyped(event.key, active) : movedIndex(event.key, active, options.length)
    if (moved === null || moved < 0) return
    event.preventDefault()
    setActive(moved)
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const printable = isTypeaheadKey(event)
    const command = listCommand(event.key, event.altKey)
    if (!open) handleClosedKey(event, printable)
    else if (command) runListCommand(event, command)
    else moveWithKey(event, printable)
  }

  return (
    <div className="rule-picker" data-clearable={clearable || undefined}>
      <div
        ref={comboRef}
        id={comboId}
        role="combobox"
        tabIndex={0}
        aria-labelledby={labelId}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listId}
        aria-activedescendant={open ? `${id}-option-${active}` : undefined}
        className="rule-picker-trigger"
        onClick={() => (open ? setOpen(false) : show(Math.max(selectedIndex, 0)))}
        onKeyDown={handleKeyDown}
        onBlur={() => setOpen(false)}
      >
        {selected && <RuleOptionContent option={selected} showAccounts={false} />}
        <ChevronDown aria-hidden="true" className="rule-picker-chevron" data-open={open} />
      </div>
      {/* A sibling rather than a child: a combobox cannot contain another control. */}
      {clearable && !open && (
        <button
          type="button"
          className="rule-picker-clear"
          aria-label={clearLabel}
          title={clearLabel}
          onClick={clear}
        >
          <X aria-hidden="true" />
        </button>
      )}
      <div
        ref={listRef}
        id={listId}
        role="listbox"
        aria-labelledby={labelId}
        className="rule-picker-list"
        hidden={!open}
      >
        <RulePickerOptions
          id={id}
          options={options}
          selectedValue={selected?.value}
          open={open}
          active={active}
          showAccounts={showAccounts}
          onActivate={setActive}
          onChoose={choose}
        />
      </div>
    </div>
  )
}

/** Clearing is offered once a known option other than the unfiltered value is chosen. */
function canClear(value: string, clearValue: string | undefined, selectedIndex: number): boolean {
  return clearValue !== undefined && value !== clearValue && selectedIndex >= 0
}

/** The listbox's options: current rules first, then removed ones in their own group. */
function RulePickerOptions({
  id,
  options,
  selectedValue,
  open,
  active,
  showAccounts,
  onActivate,
  onChoose,
}: {
  id: string
  options: RulePickerOption[]
  selectedValue: string | undefined
  open: boolean
  active: number
  showAccounts: boolean
  onActivate: (index: number) => void
  onChoose: (index: number) => void
}) {
  const current = options.filter((option) => !option.removed)
  const removed = options.filter((option) => option.removed)

  function renderOption(option: RulePickerOption) {
    const index = options.indexOf(option)
    const isSelected = option.value === selectedValue
    return (
      <div
        key={option.value || "all"}
        id={`${id}-option-${index}`}
        role="option"
        aria-selected={isSelected}
        data-index={index}
        data-active={open && index === active}
        className="rule-picker-option"
        // Keep focus on the combobox while choosing with the pointer.
        onMouseDown={(event) => event.preventDefault()}
        onMouseMove={() => onActivate(index)}
        onClick={() => onChoose(index)}
      >
        <RuleOptionContent option={option} showAccounts={showAccounts} />
        <Check aria-hidden="true" className="rule-picker-check" data-visible={isSelected} />
      </div>
    )
  }

  return (
    <>
      {current.map(renderOption)}
      {removed.length > 0 && (
        <div role="group" aria-labelledby={`${id}-removed`} className="rule-picker-group">
          <div id={`${id}-removed`} role="presentation" className="rule-picker-group-label">
            Removed rules
          </div>
          {removed.map(renderOption)}
        </div>
      )}
    </>
  )
}

function RuleOptionContent({ option, showAccounts }: { option: RulePickerOption; showAccounts: boolean }) {
  if (!option.source || !option.destination) {
    return <span className={cn("rule-picker-text", option.removed && "rule-picker-muted")}>{option.name}</span>
  }
  return (
    <>
      <span className="rule-picker-direction" aria-hidden="true">
        <PickerEndpoint endpoint={option.source} showAccount={showAccounts} />
        <ArrowRight className="rule-picker-arrow" />
        <PickerEndpoint endpoint={option.destination} showAccount={showAccounts} />
      </span>
      <span className="sr-only">{option.name}</span>
    </>
  )
}

function PickerEndpoint({ endpoint, showAccount }: { endpoint: RulePickerEndpoint; showAccount: boolean }) {
  const email = endpoint.account?.email ?? endpoint.accountId
  return (
    <span className="rule-picker-endpoint">
      <AccountAvatar
        displayName={endpoint.account?.display_name ?? ""}
        email={email}
        avatarUrl={endpoint.account?.avatar_url}
        compact
      />
      <span className="rule-picker-endpoint-copy">
        <span className="rule-picker-calendar">{endpoint.calendar}</span>
        {showAccount && <span className="rule-picker-account">{email}</span>}
      </span>
    </span>
  )
}
