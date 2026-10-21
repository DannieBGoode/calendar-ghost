import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useId, useState } from "react"
import { SignInProviderButton } from "@/components/sign-in-provider-button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useI18n } from "@/i18n/provider"
import { api, type SessionStatus } from "@/lib/api"
import { enabledSignInProviders } from "@/lib/sign-in-providers"

/** Only enabled, configured methods are advertised. Proofs stay in server-set HttpOnly cookies. */
export function ProviderSignInOptions({ invitation, isCurrent }: {
  invitation?: { token: string; email: string }; isCurrent?: () => boolean
}) {
  const { t } = useI18n()
  const providers = useQuery({ queryKey: ["sign-in-providers"], queryFn: api.signInProviders, staleTime: 0 })
  const begin = useBeginProvider(invitation, isCurrent)
  const enabled = enabledSignInProviders(providers.data)
  const ready = !invitation || /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(invitation.email.trim())
  if (!enabled.length) return null
  return <div className="provider-sign-in-options">
    <div className="provider-sign-in-buttons">{enabled.map(provider => <SignInProviderButton key={provider} provider={provider} pending={begin.isPending} unavailable={!ready} onClick={() => begin.mutate(provider)} />)}</div>
    <p className="field-hint">{t("auth.provider.calendarStep")}</p>
    <p role="status" className={begin.isPending ? "field-hint" : "sr-only"}>{begin.isPending ? t("auth.pleaseWait") : ""}</p>
    {begin.error && <p className="inline-error" role="alert">{t("auth.provider.unavailable")}</p>}
  </div>
}

/** Kept separate from password Invitation usability: provider admission rechecks the bearer link. */
export function InvitationProviderOptions({ token, isCurrent }: { token: string; isCurrent: (token: string) => boolean }) {
  const { t } = useI18n()
  const id = useId()
  const [email, setEmail] = useState("")
  const providers = useQuery({ queryKey: ["sign-in-providers"], queryFn: api.signInProviders })
  if (!token || !enabledSignInProviders(providers.data).length) return null
  return <div className="invitation-provider-options">
    <div className="field-stack"><Label htmlFor={id}>{t("auth.provider.invitationEmail")}</Label><Input id={id} type="email" autoComplete="email" value={email} onChange={event => setEmail(event.target.value)} maxLength={254} required aria-describedby={`${id}-hint`} /><p id={`${id}-hint`} className="field-hint">{t("auth.provider.invitationBinding")}</p></div>
    <ProviderSignInOptions invitation={{ token, email }} isCurrent={() => isCurrent(token)} />
  </div>
}

export function ProviderSignInFailure() {
  const { t } = useI18n()
  const [failed] = useState(() => new URLSearchParams(window.location.search).get("provider_result") === "unavailable")
  return failed ? <p className="inline-error" role="alert">{t("auth.provider.unavailable")}</p> : null
}

function useBeginProvider(invitation: { token: string; email: string } | undefined, isCurrent: (() => boolean) | undefined) {
  const client = useQueryClient()
  const owner = client.getQueryData<SessionStatus>(["session"])?.user?.id
  const begin = useMutation({
    mutationFn: async (provider: string) => {
      const answer = await api.startProviderSignIn(provider, invitation ? { invitation_token: invitation.token, email: invitation.email.trim() } : undefined)
      if ((!isCurrent || isCurrent()) && client.getQueryData<SessionStatus>(["session"])?.user?.id === owner) window.location.assign(answer.authorization_url)
      // The authorization URL contains a state proof; never retain it in the mutation cache.
    },
    retry: false, gcTime: 0,
  })
  return begin
}
