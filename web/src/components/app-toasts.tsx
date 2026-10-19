import type { ReactNode } from "react"

import { ToastProvider } from "@/components/ui/toast"
import { useI18n } from "@/i18n/provider"

/** The signed-in app's page-level results, one toast at a time, in the active language. */
export function AppToasts({ children }: { children: ReactNode }) {
  const { t } = useI18n()
  return <ToastProvider closeLabel={t("common.toast.close")}>{children}</ToastProvider>
}
