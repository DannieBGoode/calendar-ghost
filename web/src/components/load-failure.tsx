import { RefreshCw } from "lucide-react"

import { Button } from "@/components/ui/button"

export function LoadFailure({ title, onRetry }: { title: string; onRetry?: () => void }) {
  return (
    <section className="page-section" role="alert">
      <h1>{title}</h1>
      <p className="page-intro">Check that the local service is running, then try again.</p>
      <Button variant="outline" onClick={onRetry ?? (() => window.location.reload())}>
        <RefreshCw aria-hidden="true" /> Try again
      </Button>
    </section>
  )
}
