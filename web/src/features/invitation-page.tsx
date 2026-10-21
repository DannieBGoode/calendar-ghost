import { useQuery } from "@tanstack/react-query"
import { UserPlus } from "lucide-react"
import { useState } from "react"

import { AuthFrame } from "@/components/auth-frame"
import { Button } from "@/components/ui/button"
import { InvitationAcceptForm } from "@/features/invitation-accept-form"
import { InvitationProviderOptions } from "@/features/provider-sign-in-options"
import { InvitationRecovery } from "@/features/invitation-recovery"
import { RegistrationRequestForm } from "@/features/registration-request-form"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import type { LinkStatus } from "@/lib/public-links"
import { api, type ApiError } from "@/lib/api"
import { invitationSignInProviders } from "@/lib/sign-in-providers"
import { useLinkCheck, useLinkToken } from "@/lib/use-link-check"

export function InvitationPage({ onSignedIn }: { onSignedIn: () => void }) {
  const { token, isCurrent } = useLinkToken()
  return <InvitationLink key={token} token={token} isCurrent={isCurrent} onSignedIn={onSignedIn} />
}

type LinkProps = { token: string; isCurrent: (token: string) => boolean; onSignedIn: () => void }

function InvitationLink({ token, isCurrent, onSignedIn }: LinkProps) {
  const i18n = useI18n()
  const { t } = i18n
  const providerAlternative = useProviderAlternative(token)
  const check = useLinkCheck("invitation", token)
  const [email, setEmail] = useState("")
  const [refusal, setRefusal] = useState<ApiError | null>(null)
  const refused = check.status === "unusable" || refusal !== null
  const formUsable = check.status === "usable" && !refused
  const verified = isVerifiedInvitation(check.data)
  const recheck = () => { if (isCurrent(token)) void check.recheck() }
  return (
    <AuthFrame heading={t("auth.invitation.heading")} intro={t("auth.invitation.intro")}
      {...invitationPanel(t, refused && !providerAlternative, verified)} icon={UserPlus}>
      <InvitationProviderFallback status={check.status} providerAlternative={providerAlternative} token={token} isCurrent={isCurrent} />
      <InvitationCheckState status={check.status} error={check.error} onRecheck={recheck} />
      {refusal && <p className="inline-error" role="alert">{apiErrorMessage(i18n, refusal)}</p>}
      {refused && <InvitationRecovery />}
      {formUsable && (verified
        ? <RegistrationRequestForm invitationToken={token} initialEmail={email} onEmail={setEmail} isCurrent={isCurrent} onUnavailable={recheck} />
        : <InvitationAcceptForm token={token} isCurrent={isCurrent} onSignedIn={onSignedIn} email={email} onEmail={setEmail} onRecheck={recheck} onUnusable={setRefusal} />)}
      {formUsable && <div className="mt-6"><Button variant="ghost" size="lg" asChild><a href="/">{t("auth.invitation.signIn")}</a></Button></div>}
    </AuthFrame>
  )
}

function invitationPanel(t: ReturnType<typeof useI18n>["t"], refused: boolean, verified: boolean) {
  if (refused) return { panelTitle: t("auth.invitation.unusable.title"), panelNote: t("auth.invitation.unusable.body") }
  if (verified) return { panelTitle: t("auth.signUp.panel"), panelNote: t("auth.invitation.verifiedNote") }
  return { panelTitle: t("auth.invitation.panel"), panelNote: t("auth.invitation.note") }
}

function InvitationCheckState({ status, error, onRecheck }: { status: LinkStatus; error: unknown; onRecheck: () => void }) {
  const i18n = useI18n()
  const { t } = i18n
  if (status === "checking") return <p role="status">{t("auth.invitation.checking")}</p>
  if (status !== "failed") return null
  return <div className="auth-form"><p className="inline-error" role="alert">{apiErrorMessage(i18n, error)}</p><Button onClick={onRecheck}>{t("auth.registration.tryAgain")}</Button><Button variant="ghost" asChild><a href="/">{t("auth.invitation.signIn")}</a></Button></div>
}

function InvitationProviderFallback({ status, providerAlternative, token, isCurrent }: { status: LinkStatus; providerAlternative: boolean; token: string; isCurrent: (token: string) => boolean }) {
  const { t } = useI18n()
  if (!providerAlternative || status !== "unusable") return null
  return <div className="invitation-provider-fallback"><p className="field-hint">{t("auth.provider.invitationPasswordUnavailable")}</p><InvitationProviderOptions token={token} isCurrent={isCurrent} /></div>
}

function useProviderAlternative(token: string) {
  const providers = useQuery({ queryKey: ["sign-in-providers"], queryFn: api.signInProviders })
  return token !== "" && invitationSignInProviders(providers.data).length > 0
}

function isVerifiedInvitation(data: { acceptance: string | null } | undefined) { return data?.acceptance === "verified" }
