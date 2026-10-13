import { ListFilter } from "lucide-react"
import { useState } from "react"

import { Button } from "@/components/ui/button"
import { useI18n } from "@/i18n/provider"
import type { MessageKey } from "@/i18n/types"
import {
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
  onToggle,
}: {
  label: string
  count: number
  pressed: boolean
  onToggle: () => void
}) {
  const { t, format } = useI18n()
  return (
    <button
      type="button"
      className="rule-preview-option"
      aria-pressed={pressed}
      aria-label={t("rulePreview.filters.chip", { label, count: format.number(count) })}
      disabled={count === 0 && !pressed}
      onClick={onToggle}
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
  onChange,
}: {
  counts: Record<PreviewShow, number>
  show: PreviewShow
  onChange: (show: PreviewShow) => void
}) {
  const { t } = useI18n()
  return (
    <div className="rule-preview-segments" role="group" aria-label={t("rulePreview.filters.show")}>
      {(["all", "sync", "out"] as const).map((each) => (
        <FilterOption
          key={each}
          label={t(SHOW_WORDS[each])}
          count={counts[each]}
          pressed={show === each}
          onToggle={() => onChange(each)}
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
  const [kindsOpen, setKindsOpen] = useState(false)
  const counts = facetCounts(items, filters)
  const kinds = PREVIEW_KINDS.filter((kind) => tally(items, previewKinds).has(kind))
  const chosen = new Set(filters.kinds)
  const openKinds = kindsOpen || chosen.size > 0

  function toggleKind(kind: PreviewKind) {
    const next = chosen.has(kind) ? filters.kinds.filter((each) => each !== kind) : [...filters.kinds, kind]
    onChange({ ...filters, kinds: next })
  }

  return (
    <div className="rule-preview-filters">
      <div className="rule-preview-filter-row">
        <ShowChoice counts={counts.show} show={filters.show} onChange={(show) => onChange({ ...filters, show })} />
        {kinds.length > 0 && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="rule-preview-kind-toggle"
            aria-expanded={openKinds}
            aria-controls={openKinds ? "rule-preview-kinds" : undefined}
            onClick={() => setKindsOpen(!openKinds)}
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
          <Button type="button" variant="ghost" size="sm" className="rule-preview-clear" onClick={() => onChange({ show: "all", kinds: [] })}>
            {t("rulePreview.filters.clear")}
          </Button>
        </p>
      )}
    </div>
  )
}
