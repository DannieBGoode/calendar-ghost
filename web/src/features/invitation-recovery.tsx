import { useQuery } from "@tanstack/react-query"

import { Button } from "@/components/ui/button"
import { useI18n } from "@/i18n/provider"
import { api } from "@/lib/api"

export function InvitationRecovery() {
  const { t } = useI18n()
  const setup = useQuery({ queryKey: ["setup"], queryFn: api.setup, refetchOnMount: "always" })
  return <div className="auth-form">
    <p className="field-hint">{t("auth.invitation.recovery")}</p>
    <Button size="lg" asChild><a href="/">{t("auth.invitation.signIn")}</a></Button>
    {setup.data?.password_reset_available && <Button variant="ghost" asChild><a href="/forgot-password">{t("auth.forgotPassword.heading")}</a></Button>}
  </div>
}
