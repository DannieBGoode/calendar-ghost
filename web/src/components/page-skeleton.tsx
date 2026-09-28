import { Skeleton } from "@/components/ui/skeleton"

export function PageSkeleton({ label = "Loading" }: { label?: string }) {
  return (
    <div className="page-section" role="status" aria-busy="true">
      <span className="sr-only">{label}…</span>
      <Skeleton className="h-4 w-24" />
      <Skeleton className="h-10 w-80 max-w-full" />
      <Skeleton className="h-20 w-full" />
      <Skeleton className="h-72 w-full" />
    </div>
  )
}
