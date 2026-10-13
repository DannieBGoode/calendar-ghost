import { ListFilter } from "lucide-react"
import { useRef, useState, type KeyboardEvent, type RefObject } from "react"

import { Button } from "@/components/ui/button"
import { useI18n } from "@/i18n/provider"
import type { MessageKey } from "@/i18n/types"
import {
  NO_FILTERS,
  PREVIEW_KINDS,
  facetCounts,
  isFiltered,
  previewKinds,
  tally,
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

/**
 * A choice with how many rows it would show beside the other choices. One that would show none is
 * disabled, unless chosen, so it can always be undone.
 */
function FilterOption({
  label,
  count,
  pressed,
  radio = false,
  onToggle,
  onKeyDown,
}: {
  label: string
  count: number
  pressed: boolean
  /** One choice of several, which a press cannot undo, rather than an on/off toggle. */
  radio?: boolean
  onToggle: () => void
  onKeyDown?: (event: KeyboardEvent<HTMLButtonElement>) => void
}) {
  const { t, format } = useI18n()
  // Stays in the tab order, so keyboard and screen reader users meet it and hear its 0.
  const empty = count === 0 && !pressed
  return (
    <button
      type="button"
      className="rule-preview-option"
      role={radio ? "radio" : undefined}
      aria-checked={radio ? pressed : undefined}
      aria-pressed={radio ? undefined : pressed}
      // In a radio group only the chosen one is a tab stop; the arrow keys move between them.
      tabIndex={radio && !pressed ? -1 : undefined}
      onKeyDown={onKeyDown}
      aria-label={t("rulePreview.filters.chip", { label, count: format.number(count) })}
      aria-disabled={empty ? true : undefined}
      onClick={() => !empty && onToggle()}
    >
      <span>{label}</span>
      <CountBadge count={count} />
    </button>
  )
}

/** One choice of three, joined so it reads as a single control rather than three toggles. */
function ShowChoice({
  counts,
  show,
  groupRef,
  onChange,
}: {
  counts: Record<PreviewShow, number>
  show: PreviewShow
  groupRef: RefObject<HTMLDivElement | null>
  onChange: (show: PreviewShow) => void
}) {
  const { t } = useI18n()
  // The arrow keys, Home, and End choose and focus the next one that would show something.
  function move(event: KeyboardEvent<HTMLButtonElement>, from: number) {
    const open = SHOWS.filter((each) => counts[each] > 0 || each === show)
    const at = open.indexOf(SHOWS[from] ?? "all")
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key]
    const target = event.key === "Home" ? open[0] : event.key === "End" ? open.at(-1) : step ? open[(at + step + open.length) % open.length] : undefined
    if (!target) return
    event.preventDefault()
    onChange(target)
    groupRef.current?.querySelectorAll<HTMLButtonElement>("[role=radio]")[SHOWS.indexOf(target)]?.focus()
  }
  return (
    <div ref={groupRef} className="rule-preview-segments" role="radiogroup" aria-label={t("rulePreview.filters.show")}>
      {SHOWS.map((each, index) => (
        <FilterOption
          key={each}
          label={t(SHOW_WORDS[each])}
          count={counts[each]}
          pressed={show === each}
          radio
          onToggle={() => onChange(each)}
          onKeyDown={(event) => move(event, index)}
        />
      ))}
    </div>
  )
}

/**
 * Show narrows to what the destination will or will not hold; Kind, folded until wanted, to any of
 * the chosen kinds. Every count follows the other choices, so a number always says what a click
 * will show. A kind exists only when the whole preview has it, so options never vanish.
 */
export function PreviewFilterBar({
  items,
  filters,
  shown,
  onChange,
}: {
  items: readonly PreviewItem[]
  filters: PreviewFilters
  shown: number
  onChange: (filters: PreviewFilters) => void
}) {
  const { t, format } = useI18n()
  // Opens with chosen kinds, then follows the toggle alone, so it always answers and never folds
  // away under the chip just unpressed.
  const [openKinds, setOpenKinds] = useState(filters.kinds.length > 0)
  const showGroup = useRef<HTMLDivElement>(null)
  const counts = facetCounts(items, filters)
  const kinds = PREVIEW_KINDS.filter((kind) => tally(items, previewKinds).has(kind))
  const chosen = new Set(filters.kinds)

  function clear() {
    // The line holding Clear leaves with the filters, so focus goes to the choice it reset.
    showGroup.current?.querySelector<HTMLButtonElement>("[role=radio]")?.focus()
    onChange(NO_FILTERS)
  }

  function toggleKind(kind: PreviewKind) {
    const next = chosen.has(kind) ? filters.kinds.filter((each) => each !== kind) : [...filters.kinds, kind]
    onChange({ ...filters, kinds: next })
  }

  return (
    <div className="rule-preview-filters">
      <div className="rule-preview-filter-row">
        <ShowChoice
          counts={counts.show}
          show={filters.show}
          groupRef={showGroup}
          onChange={(show) => onChange({ ...filters, show })}
        />
        {kinds.length > 0 && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="rule-preview-kind-toggle"
            aria-expanded={openKinds}
            aria-controls={openKinds ? "rule-preview-kinds" : undefined}
            onClick={() => setOpenKinds(!openKinds)}
          >
            <ListFilter aria-hidden="true" />
            {t("rulePreview.filters.kindToggle")}
            {chosen.size > 0 && (
              <>
                <CountBadge count={chosen.size} />
                <span className="sr-only">{t("rulePreview.filters.kindActive", { count: chosen.size })}</span>
              </>
            )}
          </Button>
        )}
      </div>
      {openKinds && (
        <div id="rule-preview-kinds" className="rule-preview-filter-row" role="group" aria-label={t("rulePreview.filters.kind")}>
          {kinds.map((kind) => (
            <FilterOption
              key={kind}
              label={t(KIND_WORDS[kind])}
              count={counts.kinds.get(kind) ?? 0}
              pressed={chosen.has(kind)}
              onToggle={() => toggleKind(kind)}
            />
          ))}
        </div>
      )}
      {isFiltered(filters) && (
        <p className="rule-preview-showing">
          {t("rulePreview.filters.showing", { shown: format.number(shown), total: format.number(items.length) })}
          <Button type="button" variant="ghost" size="sm" className="rule-preview-clear" onClick={clear}>
            {t("rulePreview.filters.clear")}
          </Button>
        </p>
      )}
    </div>
  )
}
