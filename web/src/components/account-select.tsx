import { Check, ChevronDown } from "lucide-react"
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

/** A select-only account combobox whose options retain the connected account identity. */
export function AccountSelect({
  id: comboId,
  labelId,
  value,
  accounts,
  onChange,
}: {
  id: string
  labelId: string
  value: string
  accounts: ConnectedAccount[]
  onChange: (value: string) => void
}) {
  const id = useId()
  const listId = `${id}-list`
  const listRef = useRef<HTMLDivElement>(null)
  const typed = useRef({ text: "", at: 0 })
  const [open, setOpen] = useState(false)
  const selectedIndex = accounts.findIndex((account) => account.id === value)
  const selected = accounts[selectedIndex] ?? accounts[0]
  const [active, setActive] = useState(() => Math.max(selectedIndex, 0))
  const activeIndex = Math.min(active, Math.max(accounts.length - 1, 0))

  useEffect(() => {
    if (!open) return
    listRef.current?.querySelector(`[data-index="${activeIndex}"]`)?.scrollIntoView({ block: "nearest" })
  }, [open, activeIndex])

  function show(index: number) {
    if (!accounts.length) return
    setActive(Math.min(index, accounts.length - 1))
    setOpen(true)
  }

  function choose(index: number) {
    setOpen(false)
    const account = accounts[index]
    if (account && account.id !== value) onChange(account.id)
  }

  function findTyped(key: string, from: number): number {
    const now = Date.now()
    typed.current = { text: now - typed.current.at < 600 ? typed.current.text + key : key, at: now }
    return typeaheadIndex(
      accounts.map((account) => `${account.display_name} ${account.email}`),
      typed.current.text,
      from,
    )
  }

  function openWithKey(event: KeyboardEvent<HTMLButtonElement>, printable: boolean) {
    const index = printable
      ? findTyped(event.key, selectedIndex)
      : openingIndex(event.key, event.altKey, selectedIndex, accounts.length)
    if (index === null || index < 0) return
    event.preventDefault()
    show(index)
  }

  function runListCommand(event: KeyboardEvent<HTMLButtonElement>, command: ListCommand) {
    // Tab keeps its default so focus still moves on.
    if (command !== "chooseAndLeave") event.preventDefault()
    if (command === "close") setOpen(false)
    else choose(activeIndex)
  }

  function moveWithKey(event: KeyboardEvent<HTMLButtonElement>, printable: boolean) {
    const moved = printable ? findTyped(event.key, activeIndex) : movedIndex(event.key, activeIndex, accounts.length)
    if (moved === null || moved < 0) return
    event.preventDefault()
    setActive(moved)
  }

  function handleKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    const printable = isTypeaheadKey(event)
    const command = listCommand(event.key, event.altKey)
    if (!open) openWithKey(event, printable)
    else if (command) runListCommand(event, command)
    else moveWithKey(event, printable)
  }

  return (
    <div className="account-select">
      <button
        type="button"
        id={comboId}
        role="combobox"
        aria-labelledby={labelId}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listId}
        aria-activedescendant={open ? `${id}-option-${activeIndex}` : undefined}
        className="account-select-trigger"
        onClick={() => (open ? setOpen(false) : show(Math.max(selectedIndex, 0)))}
        onKeyDown={handleKeyDown}
        onBlur={() => setOpen(false)}
      >
        {selected ? <AccountOptionContent account={selected} /> : <span>No Google accounts</span>}
        <ChevronDown aria-hidden="true" className="account-select-chevron" data-open={open} />
      </button>
      <div
        ref={listRef}
        id={listId}
        role="listbox"
        aria-labelledby={labelId}
        className="account-select-list"
        hidden={!open}
      >
        {accounts.map((account, index) => {
          const isSelected = account.id === selected?.id
          return (
            <div
              key={account.id}
              id={`${id}-option-${index}`}
              role="option"
              aria-selected={isSelected}
              data-index={index}
              data-active={open && index === activeIndex}
              className="account-select-option"
              onMouseDown={(event) => event.preventDefault()}
              onMouseMove={() => setActive(index)}
              onClick={() => choose(index)}
            >
              <AccountOptionContent account={account} />
              <Check aria-hidden="true" className="account-select-check" data-visible={isSelected} />
            </div>
          )
        })}
      </div>
    </div>
  )
}

function AccountOptionContent({ account }: { account: ConnectedAccount }) {
  return (
    <span className="account-select-option-content">
      <AccountAvatar
        displayName={account.display_name}
        email={account.email}
        avatarUrl={account.avatar_url}
        compact
      />
      <span className="account-select-copy">
        <span className="account-select-name">{account.display_name}</span>
        <span className="account-select-email">{account.email}</span>
      </span>
    </span>
  )
}
