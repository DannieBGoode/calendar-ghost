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

/**
 * Show narrows to what the destination will or will not hold; Kind to any of the chosen kinds.
 * A chip exists only when the whole preview has its kind, so chips never vanish while filtering.
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
  const synced = items.filter((item) => item.projection).length
  const showCounts: Record<PreviewShow, number> = { all: items.length, sync: synced, out: items.length - synced }
  const kindCounts = tally(items, previewKinds)
  const kinds = PREVIEW_KINDS.filter((kind) => kindCounts.has(kind))
  const chosen = new Set(filters.kinds)
  const shows = (["all", "sync", "out"] as const).filter((show) => show === "all" || showCounts[show] > 0)

  function toggleKind(kind: PreviewKind) {
    const kinds = chosen.has(kind) ? filters.kinds.filter((each) => each !== kind) : [...filters.kinds, kind]
    onChange({ ...filters, kinds })
  }

  return (
    <div className="rule-preview-filters">
      <div className="rule-preview-filter-row" role="group" aria-labelledby="rule-preview-show">
        <span id="rule-preview-show" className="rule-preview-filter-label">{t("rulePreview.filters.show")}</span>
        {shows.map((show) => (
          <FilterChip
            key={show}
            label={t(SHOW_WORDS[show])}
            count={showCounts[show]}
            pressed={filters.show === show}
            onToggle={() => onChange({ ...filters, show })}
          />
        ))}
      </div>
      {kinds.length > 0 && (
        <div className="rule-preview-filter-row" role="group" aria-labelledby="rule-preview-kind">
          <span id="rule-preview-kind" className="rule-preview-filter-label">{t("rulePreview.filters.kind")}</span>
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
