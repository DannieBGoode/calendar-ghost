import { UserPlus } from "lucide-react"
import { useState } from "react"

import { AuthFrame } from "@/components/auth-frame"
import { Button } from "@/components/ui/button"
import { InvitationAcceptForm } from "@/features/invitation-accept-form"
import { InvitationRecovery } from "@/features/invitation-recovery"
import { RegistrationRequestForm } from "@/features/registration-request-form"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import type { LinkStatus } from "@/lib/public-links"
import type { ApiError } from "@/lib/api"
import { useLinkCheck, useLinkToken } from "@/lib/use-link-check"

export function InvitationPage({ onSignedIn }: { onSignedIn: () => void }) {
  const { token, isCurrent } = useLinkToken()
  return <InvitationLink key={token} token={token} isCurrent={isCurrent} onSignedIn={onSignedIn} />
}

type LinkProps = { token: string; isCurrent: (token: string) => boolean; onSignedIn: () => void }

function InvitationLink({ token, isCurrent, onSignedIn }: LinkProps) {
  const i18n = useI18n()
  const { t } = i18n
  const check = useLinkCheck("invitation", token)
  const [email, setEmail] = useState("")
  const [refusal, setRefusal] = useState<ApiError | null>(null)
  const refused = check.status === "unusable" || refusal !== null
  const verified = check.data?.acceptance === "verified"
  const recheck = () => { if (isCurrent(token)) void check.recheck() }
  return (
    <AuthFrame heading={t("auth.invitation.heading")} intro={t("auth.invitation.intro")}
      {...invitationPanel(t, refused, verified)} icon={UserPlus}>
      <InvitationCheckState status={check.status} error={check.error} onRecheck={recheck} />
      {refusal && <p className="inline-error" role="alert">{apiErrorMessage(i18n, refusal)}</p>}
      {refused && <InvitationRecovery />}
      {check.status === "usable" && !refused && (verified
        ? <RegistrationRequestForm invitationToken={token} initialEmail={email} onEmail={setEmail} isCurrent={isCurrent} onUnavailable={recheck} />
        : <InvitationAcceptForm token={token} isCurrent={isCurrent} onSignedIn={onSignedIn} email={email} onEmail={setEmail} onRecheck={recheck} onUnusable={setRefusal} />)}
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
