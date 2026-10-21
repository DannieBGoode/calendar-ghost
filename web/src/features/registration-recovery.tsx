import { useQuery } from "@tanstack/react-query"

import { Button } from "@/components/ui/button"
import { useI18n } from "@/i18n/provider"
import { api } from "@/lib/api"

/** A spent proof cannot create another account; existing accounts recover at sign-in. */
export function RegistrationRecovery({ sessionFailed }: { sessionFailed: boolean }) {
  const { t } = useI18n()
  const setup = useQuery({ queryKey: ["setup"], queryFn: api.setup, enabled: !sessionFailed, refetchOnMount: "always" })
  const available = !setup.error && setup.data?.administrator_configured && setup.data.public_registration_available
  return <div className="auth-form">
    {!sessionFailed && available && <Button size="lg" asChild><a href="/sign-up">{t("auth.registration.requestNew")}</a></Button>}
    <Button size="lg" variant={available && !sessionFailed ? "outline" : "default"} asChild><a href="/">{t("auth.signIn")}</a></Button>
    {setup.data?.password_reset_available && <Button variant="ghost" asChild><a href="/forgot-password">{t("auth.forgotPassword.heading")}</a></Button>}
  </div>
}
