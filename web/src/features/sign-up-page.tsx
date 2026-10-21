import { useQuery } from "@tanstack/react-query"
import { UserPlus } from "lucide-react"

import { AuthFrame } from "@/components/auth-frame"
import { Button } from "@/components/ui/button"
import { ProviderSignInOptions } from "@/features/provider-sign-in-options"
import { RegistrationRequestForm } from "@/features/registration-request-form"
import { useI18n } from "@/i18n/provider"
import { api } from "@/lib/api"

/** Refresh admission when entering; cached sign-in availability never authorizes joining. */
export function SignUpPage() {
  const { t } = useI18n()
  const setup = useQuery({ queryKey: ["setup", "sign-up"], queryFn: api.setup, refetchOnMount: "always", refetchOnWindowFocus: false, gcTime: 0 })
  const available = !setup.isFetching && !setup.error && setup.data?.public_registration_available === true
  return (
    <AuthFrame heading={t("auth.signUp.heading")} intro={t("auth.signUp.intro")}
      panelTitle={t(available || setup.isFetching ? "auth.signUp.panel" : "auth.signUp.unavailableTitle")}
      panelNote={t(available || setup.isFetching ? "auth.signUp.note" : "auth.signUp.unavailable")} icon={UserPlus}>
      {setup.isFetching && <p role="status">{t("auth.pleaseWait")}</p>}
      {available && <><ProviderSignInOptions /><RegistrationRequestForm onUnavailable={() => { void setup.refetch() }} /></>}
      <div className="mt-6"><Button variant="ghost" size="lg" asChild><a href="/">{t("auth.forgotPassword.signIn")}</a></Button></div>
    </AuthFrame>
  )
}
