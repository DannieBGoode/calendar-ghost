import { Fragment, useRef, type KeyboardEvent } from "react"

import { useI18n } from "@/i18n/provider"
import type { MessageKey } from "@/i18n/types"
import type { PreviewView } from "@/lib/rule-preview"

const VIEW_WORDS: Record<PreviewView, MessageKey> = {
  all: "rulePreview.filters.all",
  sync: "rulePreview.filters.sync",
  out: "rulePreview.filters.out",
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
 * Which rows the table shows, one view at a time: All, Will sync, Not synced, then each kind this
 * preview has. One choice means the counts never move, no option leads to an empty table but an
 * outcome view with 0, and nothing appears or leaves beside the row when it changes. It is a radio
 * group: one tab stop, with the arrow keys, Home, and End choosing among the views that show rows.
 */
export function PreviewViewChoice({
  views,
  view,
  onChange,
}: {
  /** The views this preview offers, with their counts, as `previewViews` gives them. */
  views: readonly { view: PreviewView; count: number }[]
  view: PreviewView
  onChange: (view: PreviewView) => void
}) {
  const { t, format } = useI18n()
  const group = useRef<HTMLDivElement>(null)
  const open = views.filter((each) => each.count > 0 || each.view === view).map((each) => each.view)

  function choose(next: PreviewView) {
    onChange(next)
    group.current?.querySelectorAll<HTMLButtonElement>("[role=radio]")[views.findIndex((each) => each.view === next)]?.focus()
  }

  function move(event: KeyboardEvent<HTMLButtonElement>) {
    const at = open.indexOf(view)
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key]
    const target = event.key === "Home" ? open[0] : event.key === "End" ? open.at(-1) : step ? open[(at + step + open.length) % open.length] : undefined
    if (!target) return
    event.preventDefault()
    choose(target)
  }

  return (
    <div ref={group} className="rule-preview-views" role="radiogroup" aria-label={t("rulePreview.filters.show")}>
      {views.map(({ view: each, count }, index) => {
        const checked = each === view
        // An outcome view with nothing in it stays, so the row never changes shape, but cannot be chosen.
        const empty = count === 0 && !checked
        return (
          <Fragment key={each}>
            {index === 3 && <span className="rule-preview-views-divider" aria-hidden="true" />}
            <button
              type="button"
              role="radio"
              className="rule-preview-option"
              aria-checked={checked}
              aria-disabled={empty ? true : undefined}
              aria-label={t("rulePreview.filters.chip", { label: t(VIEW_WORDS[each]), count: format.number(count) })}
              tabIndex={checked ? 0 : -1}
              onClick={() => !empty && onChange(each)}
              onKeyDown={move}
            >
              <span>{t(VIEW_WORDS[each])}</span>
              <CountBadge count={count} />
            </button>
          </Fragment>
        )
      })}
    </div>
  )
}
