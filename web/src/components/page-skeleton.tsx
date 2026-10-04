import { Skeleton } from "@/components/ui/skeleton"
import { useI18n } from "@/i18n/provider"

export function PageSkeleton({ label }: { label?: string }) {
  const { t } = useI18n()
  const resolvedLabel = label ?? t("common.loading")
  return (
    <div className="page-section" role="status" aria-busy="true">
      <span className="sr-only">{resolvedLabel}…</span>
      <Skeleton className="h-4 w-24" />
      <Skeleton className="h-10 w-80 max-w-full" />
      <Skeleton className="h-20 w-full" />
      <Skeleton className="h-72 w-full" />
    </div>
  )
}
