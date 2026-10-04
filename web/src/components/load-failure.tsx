import { RefreshCw } from "lucide-react"

import { Button } from "@/components/ui/button"
import { useI18n } from "@/i18n/provider"

export function LoadFailure({ title, onRetry }: { title: string; onRetry?: () => void }) {
  const { t } = useI18n()
  return (
    <section className="page-section" role="alert">
      <h1>{title}</h1>
      <p className="page-intro">{t("common.loadFailure.body")}</p>
      <Button variant="outline" onClick={onRetry ?? (() => window.location.reload())}>
        <RefreshCw aria-hidden="true" /> {t("common.loadFailure.retry")}
      </Button>
    </section>
  )
}
