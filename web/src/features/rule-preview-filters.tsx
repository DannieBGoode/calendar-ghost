import { useRef, type KeyboardEvent } from "react"

import { useI18n } from "@/i18n/provider"
import type { MessageKey } from "@/i18n/types"
import {
  facetCounts,
  offeredKinds,
  type PreviewFilters,
  type PreviewItem,
  type PreviewKind,
  type PreviewShow,
} from "@/lib/rule-preview"

const SHOWS: readonly PreviewShow[] = ["all", "sync", "out"]

const SHOW_WORDS: Record<PreviewShow, MessageKey> = {
  all: "rulePreview.filters.all",
  sync: "rulePreview.filters.sync",
  out: "rulePreview.filters.out",
}

const KIND_WORDS: Record<PreviewKind, MessageKey> = {
  allDay: "rulePreview.filters.kinds.allDay",
  birthday: "rulePreview.filters.kinds.birthday",
  recurring: "rulePreview.filters.kinds.recurring",
  declined: "rulePreview.filters.kinds.declined",
  maybe: "rulePreview.filters.kinds.maybe",
  unanswered: "rulePreview.filters.kinds.unanswered",
}

/** A count set apart from its label, so labels line up and numbers read as numbers. */
function CountBadge({ count }: { count: number }) {
  const { format } = useI18n()
  return (
    <span className="rule-preview-count-badge" aria-hidden="true">
      {format.number(count)}
    </span>
  )
}

/** All, Will sync, or Not synced: one choice, joined into one control, read as a radio group. */
function ShowChoice({
  counts,
  show,
  onChange,
}: {
  counts: Record<PreviewShow, number>
  show: PreviewShow
  onChange: (show: PreviewShow) => void
}) {
  const { t, format } = useI18n()
  const group = useRef<HTMLDivElement>(null)
  const open = SHOWS.filter((each) => counts[each] > 0 || each === show)

  // One tab stop; the arrow keys, Home, and End choose and focus the next one that shows rows.
  function move(event: KeyboardEvent<HTMLButtonElement>) {
    const at = open.indexOf(show)
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key]
    const target = event.key === "Home" ? open[0] : event.key === "End" ? open.at(-1) : step ? open[(at + step + open.length) % open.length] : undefined
    if (!target) return
    event.preventDefault()
    onChange(target)
    group.current?.querySelectorAll<HTMLButtonElement>("[role=radio]")[SHOWS.indexOf(target)]?.focus()
  }

  return (
    <div ref={group} className="rule-preview-segments" role="radiogroup" aria-label={t("rulePreview.filters.show")}>
      {SHOWS.map((each) => {
        const checked = each === show
        const empty = counts[each] === 0 && !checked
        return (
          <button
            key={each}
            type="button"
            role="radio"
            className="rule-preview-option"
            aria-checked={checked}
            aria-disabled={empty ? true : undefined}
            aria-label={t("rulePreview.filters.chip", { label: t(SHOW_WORDS[each]), count: format.number(counts[each]) })}
            tabIndex={checked ? 0 : -1}
            onClick={() => !empty && onChange(each)}
            onKeyDown={move}
          >
            <span>{t(SHOW_WORDS[each])}</span>
            <CountBadge count={counts[each]} />
          </button>
        )
      })}
    </div>
  )
}

/**
 * One row: Show, then each kind this preview has, which combine with it and with each other ("any
 * of"). Every count follows the other choices, so the chosen Show count is always the rows shown
 * and no separate "Showing" line has to come and go. An option that would show nothing beside the
 * others stays in place, dimmed, so the row never changes shape, and cannot be pressed unless
 * chosen.
 */
export function PreviewFilterBar({
  items,
  filters,
  onChange,
}: {
  items: readonly PreviewItem[]
  filters: PreviewFilters
  onChange: (filters: PreviewFilters) => void
}) {
  const { t, format } = useI18n()
  const counts = facetCounts(items, filters)
  const kinds = offeredKinds(items)
  const chosen = new Set(filters.kinds)

  function toggleKind(kind: PreviewKind) {
    const next = chosen.has(kind) ? filters.kinds.filter((each) => each !== kind) : [...filters.kinds, kind]
    onChange({ ...filters, kinds: next })
  }

  return (
    <div className="rule-preview-filters">
      <ShowChoice counts={counts.show} show={filters.show} onChange={(show) => onChange({ ...filters, show })} />
      {kinds.length > 0 && (
        <>
          <span className="rule-preview-filters-divider" aria-hidden="true" />
          <div className="rule-preview-kinds" role="group" aria-label={t("rulePreview.filters.kind")}>
            {kinds.map((kind) => {
              const pressed = chosen.has(kind)
              const count = counts.kinds.get(kind) ?? 0
              const empty = count === 0 && !pressed
              return (
                <button
                  key={kind}
                  type="button"
                  className="rule-preview-option"
                  aria-pressed={pressed}
                  aria-disabled={empty ? true : undefined}
                  aria-label={t("rulePreview.filters.chip", { label: t(KIND_WORDS[kind]), count: format.number(count) })}
                  onClick={() => !empty && toggleKind(kind)}
                >
                  <span>{t(KIND_WORDS[kind])}</span>
                  <CountBadge count={count} />
                </button>
              )
            })}
          </div>
        </>
      )}
    </div>
  )
}
