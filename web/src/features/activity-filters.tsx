import { Search, X } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import { RulePicker, type RulePickerOption } from "@/components/rule-picker"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { NativeSelect } from "@/components/ui/native-select"
import { SHOW_FILTERS } from "@/lib/activity"
import type { ActivityLocationState, ActivityShow } from "@/lib/activity-location"
import { endpointName, type RuleContext } from "@/lib/activity-rule-context"
import type { AuditEntry, RuleSummary } from "@/lib/api"

export function ActivityFilters({
  query,
  ruleId,
  show,
  entries,
  context,
  onChange,
}: {
  query: string
  ruleId: string
  show: ActivityShow
  entries: AuditEntry[]
  context: RuleContext
  onChange: (next: Partial<ActivityLocationState>) => void
}) {
  const pickerOptions = rulePickerOptions(ruleId, entries, context)
  return (
    <div className="activity-filters">
      <ActivitySearch query={query} onSearch={(next) => onChange({ query: next })} />
      <div className="field-stack">
        <Label id="activity-rule-label" onClick={() => document.getElementById("activity-rule")?.focus()}>Rule</Label>
        <RulePicker
          id="activity-rule"
          labelId="activity-rule-label"
          value={ruleId}
          options={pickerOptions.options}
          showAccounts={pickerOptions.showAccounts}
          clearValue=""
          clearLabel="Show all rules"
          onChange={(value) => onChange({ ruleId: value })}
        />
      </div>
      <div className="field-stack">
        <Label htmlFor="activity-category">Show</Label>
        <NativeSelect id="activity-category" value={show} onChange={(event) => onChange({ show: event.target.value as ActivityShow })}>
          {SHOW_FILTERS.map((filter) => <option key={filter.value} value={filter.value}>{filter.label}</option>)}
        </NativeSelect>
      </div>
    </div>
  )
}

function rulePickerOptions(
  ruleId: string,
  entries: AuditEntry[],
  context: RuleContext,
): { options: RulePickerOption[]; showAccounts: boolean } {
  const rules = [...context.rulesById.values()]
  const endpoint = (value: RuleSummary["source"]) => ({
    calendar: endpointName(value, context),
    accountId: value.connected_account_id,
    account: context.accountsById.get(value.connected_account_id),
  })
  // History can name rules that were removed; they stay filterable.
  const removed = context.rulesLoaded
    ? [...new Set([...entries.map((item) => item.rule_id), ...(ruleId ? [ruleId] : [])])].filter(
        (id) => !context.rulesById.has(id),
      )
    : []
  const options: RulePickerOption[] = [
    { value: "", name: "All rules" },
    ...rules.map((rule) => {
      const source = endpoint(rule.source)
      const destination = endpoint(rule.destination)
      return { value: rule.id, name: `${source.calendar} to ${destination.calendar}`, source, destination }
    }),
    ...removed.map((id, index) => ({
      value: id,
      name: removed.length > 1 ? `Removed rule ${index + 1}` : "Removed rule",
      removed: true,
    })),
  ]
  // Calendar names alone cannot tell apart two calendars that share a name.
  const calendars = new Map<string, Set<string>>()
  for (const rule of rules) {
    for (const side of [rule.source, rule.destination]) {
      const name = endpointName(side, context)
      calendars.set(name, (calendars.get(name) ?? new Set()).add(`${side.connected_account_id}/${side.calendar_id}`))
    }
  }
  return { options, showAccounts: [...calendars.values()].some((ids) => ids.size > 1) }
}

const SEARCH_DELAY_MS = 300

/**
 * Searches recorded event titles as the administrator types, pausing briefly so each keystroke
 * does not replace the table. Enter searches at once; Escape clears.
 */
function ActivitySearch({ query, onSearch }: { query: string; onSearch: (query: string) => void }) {
  const [text, setText] = useState(query)
  const [shownQuery, setShownQuery] = useState(query)
  const input = useRef<HTMLInputElement>(null)
  const search = useRef(onSearch)
  useEffect(() => {
    search.current = onSearch
  })
  // A search cleared elsewhere, such as from the empty state, empties the field too.
  if (query !== shownQuery) {
    setShownQuery(query)
    if (text.trim() !== query) setText(query)
  }

  useEffect(() => {
    if (text.trim() === query) return
    const timer = window.setTimeout(() => search.current(text.trim()), SEARCH_DELAY_MS)
    return () => window.clearTimeout(timer)
  }, [text, query])

  function clear() {
    setText("")
    onSearch("")
    input.current?.focus()
  }

  return (
    <div className="field-stack">
      <Label htmlFor="activity-search">Event</Label>
      <div className="activity-search">
        <Search aria-hidden="true" className="activity-search-icon" />
        <Input
          ref={input}
          id="activity-search"
          type="search"
          value={text}
          placeholder="Search event titles"
          autoComplete="off"
          spellCheck={false}
          maxLength={200}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault()
              if (text.trim() !== query) onSearch(text.trim())
            } else if (event.key === "Escape" && text) {
              event.preventDefault()
              clear()
            }
          }}
        />
        {text && (
          <button type="button" className="activity-search-clear" aria-label="Clear search" title="Clear search" onClick={clear}>
            <X aria-hidden="true" />
          </button>
        )}
      </div>
    </div>
  )
}
