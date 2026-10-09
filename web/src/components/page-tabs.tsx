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
}

/**
 * Links to the parts of one page, underlined like the primary navigation's items. Each has its
 * own address, so they are navigation rather than an ARIA tablist; a plain click opens the part in
 * place, and any other click is left to the browser.
 */
export function PageTabs<T extends string>({
  label,
  tabs,
  current,
  onOpen,
}: {
  label: string
  tabs: PageTab<T>[]
  current: T
  onOpen: (tab: T) => void
}) {
  return (
    <nav className="page-tabs" aria-label={label}>
      {tabs.map((tab) => (
        <a
          key={tab.id}
          href={tab.href}
          className={cn("page-tab", tab.id === current && "active")}
          aria-current={tab.id === current ? "page" : undefined}
          onClick={(event) => {
            if (!isPlainLeftClick(event)) return
            event.preventDefault()
            onOpen(tab.id)
          }}
        >
          {tab.label}
          {tab.count ? (
            <Badge variant="neutral" className="page-tab-count">
              <span aria-hidden="true">{tab.count}</span>
              <span className="sr-only">{tab.countLabel}</span>
            </Badge>
          ) : null}
        </a>
      ))}
    </nav>
  )
}
