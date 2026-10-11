import { ChevronDown, ChevronUp, X } from "lucide-react"

import { Button } from "@/components/ui/button"

/** Close, then steps to the item above and below, at the top of a details panel beside a table. */
export function DetailToolbar({
  labels,
  onClose,
  onPrevious,
  onNext,
}: {
  labels: { close: string; previous: string; next: string }
  onClose: () => void
  onPrevious?: (() => void) | undefined
  onNext?: (() => void) | undefined
}) {
  return (
    <div className="activity-detail-bar">
      <Button variant="ghost" size="sm" onClick={onClose}>
        <X aria-hidden="true" /> {labels.close}
      </Button>
      <div className="activity-detail-steps">
        <Button variant="ghost" size="sm" onClick={onPrevious} disabled={!onPrevious} aria-label={labels.previous}>
          <ChevronUp aria-hidden="true" />
        </Button>
        <Button variant="ghost" size="sm" onClick={onNext} disabled={!onNext} aria-label={labels.next}>
          <ChevronDown aria-hidden="true" />
        </Button>
      </div>
    </div>
  )
}
