import { ChevronLeft, ChevronRight } from "lucide-react"

import { Button } from "@/components/ui/button"
import { useI18n } from "@/i18n/provider"
import type { PeoplePage } from "@/lib/api"
import { pageRange } from "@/lib/people-query"

/**
 * Who this page shows out of everyone who matches, and the way to the pages either side. Everyone
 * on one page needs no way to another, so then only the summary shows.
 */
export function PeoplePagination({ page, onPage }: { page: PeoplePage; onPage: (page: number) => void }) {
  const { t } = useI18n()
  const range = pageRange({ ...page, shown: page.users.length })
  return (
    <nav className="people-pagination" aria-label={t("people.pagination.label")}>
      <p>{t("people.pagination.summary", { first: range.first, last: range.last, count: page.total })}</p>
      {(range.previous || range.next) && (
        <div className="people-pagination-buttons">
          <Button type="button" variant="outline" disabled={!range.previous} onClick={() => onPage(page.page - 1)}>
            <ChevronLeft aria-hidden="true" />
            {t("people.pagination.previous")}
          </Button>
          <Button type="button" variant="outline" disabled={!range.next} onClick={() => onPage(page.page + 1)}>
            {t("people.pagination.next")}
            <ChevronRight aria-hidden="true" />
          </Button>
        </div>
      )}
    </nav>
  )
}
