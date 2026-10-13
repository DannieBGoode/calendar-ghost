import { SlidersHorizontal } from "lucide-react"
import { useState } from "react"

import { Button } from "@/components/ui/button"
import { useI18n } from "@/i18n/provider"
import type { MessageKey } from "@/i18n/types"
import {
  PREVIEW_KINDS,
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

function FilterChip({ label, count, pressed, onToggle }: { label: string; count: number; pressed: boolean; onToggle: () => void }) {
  const { t, format } = useI18n()
  return (
    <Button type="button" variant="outline" className="health-count" aria-pressed={pressed} onClick={onToggle}>
      {t("rulePreview.filters.chip", { label, count: format.number(count) })}
    </Button>
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
  const { t, format } = useI18n()
  const shows = (["all", "sync", "out"] as const).filter((each) => each === "all" || counts[each] > 0)
  return (
    <div className="rule-preview-segments" role="group" aria-label={t("rulePreview.filters.show")}>
      {shows.map((each) => (
        <button key={each} type="button" aria-pressed={show === each} onClick={() => onChange(each)}>
          {t("rulePreview.filters.chip", { label: t(SHOW_WORDS[each]), count: format.number(counts[each]) })}
        </button>
      ))}
    </div>
  )
}

/**
 * Show narrows to what the destination will or will not hold; Kind, folded until wanted, to any of
 * the chosen kinds. A kind exists only when the whole preview has it, so chips never vanish.
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
  const synced = items.filter((item) => item.projection).length
  const showCounts: Record<PreviewShow, number> = { all: items.length, sync: synced, out: items.length - synced }
  const kindCounts = tally(items, previewKinds)
  const kinds = PREVIEW_KINDS.filter((kind) => kindCounts.has(kind))
  const chosen = new Set(filters.kinds)
  const openKinds = kindsOpen || chosen.size > 0

  function toggleKind(kind: PreviewKind) {
    const next = chosen.has(kind) ? filters.kinds.filter((each) => each !== kind) : [...filters.kinds, kind]
    onChange({ ...filters, kinds: next })
  }

  return (
    <div className="rule-preview-filters">
      <div className="rule-preview-filter-row">
        <ShowChoice counts={showCounts} show={filters.show} onChange={(show) => onChange({ ...filters, show })} />
        {kinds.length > 0 && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="rule-preview-kind-toggle"
            aria-expanded={openKinds}
            aria-controls="rule-preview-kinds"
            onClick={() => setKindsOpen(!openKinds)}
          >
            <SlidersHorizontal aria-hidden="true" />
            {t("rulePreview.filters.kindToggle")}
            {chosen.size > 0 && <span className="rule-preview-kind-count">{t("rulePreview.filters.kindActive", { count: chosen.size })}</span>}
          </Button>
        )}
      </div>
      {openKinds && (
        <div id="rule-preview-kinds" className="rule-preview-filter-row" role="group" aria-label={t("rulePreview.filters.kind")}>
          {kinds.map((kind) => (
            <FilterChip
              key={kind}
              label={t(KIND_WORDS[kind])}
              count={kindCounts.get(kind) ?? 0}
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
