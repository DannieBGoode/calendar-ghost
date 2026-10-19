import { Badge } from "@/components/ui/badge"
import { isPlainLeftClick } from "@/lib/navigation"
import { cn } from "@/lib/utils"

export type PageTab<T extends string> = {
  id: T
  label: string
  href: string
  /** A count shown beside the label, such as invitations waiting; none when absent or zero. */
  count?: number
  /** What the count means, for screen readers, such as "2 waiting". */
  countLabel?: string
  /** Attention for a count of things to act on, such as open Incidents; neutral otherwise. */
  countTone?: "attention"
}

/**
 * Links to the parts of one page, underlined like the primary navigation's items. Each has its
 * own address, so they are navigation rather than an ARIA tablist; a plain click opens the part in
 * place, and any other click is left to the browser. While `waiting`, as for a command on its way
 * in the part shown, the other tabs keep focus but stay put, so its answer has a place to show.
 */
export function PageTabs<T extends string>({
  label,
  tabs,
  current,
  onOpen,
  waiting = false,
  className,
}: {
  label: string
  tabs: PageTab<T>[]
  current: T
  onOpen: (tab: T) => void
  waiting?: boolean
  className?: string
}) {
  return (
    <nav className={cn("page-tabs", className)} aria-label={label}>
      {tabs.map((tab) => (
        <a
          key={tab.id}
          href={tab.href}
          className={cn("page-tab", tab.id === current && "active")}
          aria-current={tab.id === current ? "page" : undefined}
          aria-disabled={waiting && tab.id !== current ? true : undefined}
          onClick={(event) => {
            if (!isPlainLeftClick(event)) return
            event.preventDefault()
            if (!waiting) onOpen(tab.id)
          }}
        >
          {tab.label}
          {tab.count ? (
            <Badge variant={tab.countTone ?? "neutral"} className="page-tab-count" data-tone={tab.countTone}>
              <span aria-hidden="true">{tab.count}</span>
              <span className="sr-only">{tab.countLabel}</span>
            </Badge>
          ) : null}
        </a>
      ))}
    </nav>
  )
}
