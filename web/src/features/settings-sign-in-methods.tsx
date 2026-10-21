import { useLayoutEffect, useRef } from "react"
import { useMutation, useQuery } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { PasswordItem } from "@/features/settings-own-password"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import { api } from "@/lib/api"
import { SIGN_IN_NAMES, SIGN_IN_PROVIDERS, isSignInProvider, type SignInProvider } from "@/lib/sign-in-providers"
import { useSignInMethods } from "@/lib/use-sign-in-methods"

export function SignInMethods({ userId, onDone }: { userId: string; onDone: (message: string) => void }) {
  const i18n = useI18n()
  const { t } = i18n
  const { methods, current, refresh } = useSignInMethods(userId)
  const available = useQuery({ queryKey: ["sign-in-providers"], queryFn: api.signInProviders, staleTime: 0 })
  const removal = useRemovalFocus(methods.data?.identities, current, onDone)
  if (methods.isPending) return <div className="setting-item"><Skeleton className="h-16 w-full" /></div>
  if (methods.error) return <div className="setting-item"><p role="alert">{apiErrorMessage(i18n, methods.error)}</p><Button variant="outline" onClick={() => void methods.refetch()}>{t("common.loadFailure.retry")}</Button></div>
  const enabled = new Set(available.data?.providers ?? [])
  const identities = methods.data.identities
  const linked = new Set(identities.map(identity => identity.provider))
  const usable = identities.filter(identity => enabled.has(identity.provider)).length
  const rows = identities.flatMap(identity => isSignInProvider(identity.provider) ? [{ provider: identity.provider, id: identity.id }] : [])
  const unlinked = SIGN_IN_PROVIDERS.filter(provider => enabled.has(provider) && !linked.has(provider)).map(provider => ({ provider, id: undefined }))
  return <>
    <PasswordItem hasPassword={methods.data.has_password} currentOwner={current} onDone={onDone} />
    {[...rows, ...unlinked].map(row => <ProviderMethodRow key={row.id ?? row.provider} provider={row.provider} identityId={row.id} enabled={enabled.has(row.provider)} removable={methods.data.has_password || (enabled.has(row.provider) ? usable > 1 : usable > 0)} current={current} refresh={refresh} removed={removal} onStart={() => onDone("")} />)}
    {identities.length > 0 && <div className="setting-item provider-connections-reminder"><p className="field-hint">{t("auth.provider.calendarStep")} <a className="text-link" href="/settings/connections">{t("settings.signIn.connections")}</a></p></div>}
  </>
}

type RowProps = { provider: SignInProvider; identityId: string | undefined; enabled: boolean; removable: boolean; current: () => boolean; refresh: () => Promise<void>; removed: (provider: SignInProvider, id: string, button: HTMLButtonElement | null) => void; onStart: () => void }
function ProviderMethodRow({ provider, identityId, enabled, removable, current, refresh, removed, onStart }: RowProps) {
  const i18n = useI18n()
  const { t } = i18n
  const name = t(SIGN_IN_NAMES[provider])
  const button = useRef<HTMLButtonElement>(null)
  const command = useMutation({
    mutationFn: async () => {
      if (identityId) await api.unlinkSignInProvider(identityId)
      else {
        const answer = await api.linkSignInProvider(provider)
        if (current()) window.location.assign(answer.authorization_url)
      }
    }, retry: false, gcTime: 0,
    onSuccess: () => {
      if (!current()) return
      if (identityId) removed(provider, identityId, button.current)
      void refresh()
    },
  })
  const blocked = command.isPending || cannotRemove(identityId, removable)
  return <div className="setting-item provider-method-item"><div className="setting-row"><div><h3>{name}</h3><p>{t(!identityId ? "settings.signIn.notLinked" : enabled ? "settings.signIn.linked" : "settings.signIn.unavailable")}</p></div><Button ref={button} data-sign-in-provider={provider} variant="outline" aria-disabled={blocked} aria-busy={command.isPending} onClick={() => { if (!blocked && current()) { onStart(); command.mutate() } }}>{t(identityId ? "settings.signIn.remove" : "settings.signIn.link", { provider: name })}</Button></div>
    {identityId && !removable && <p className="field-hint">{t("settings.signIn.lastMethod")}</p>}
    {identityId && !enabled && <p className="field-hint">{t("settings.signIn.recovery")}</p>}
    {command.error && <p className="field-error" role="alert">{apiErrorMessage(i18n, command.error)}</p>}
  </div>
}

function cannotRemove(identityId: string | undefined, removable: boolean) { return !!identityId && !removable }


function useRemovalFocus(identities: { id: string }[] | undefined, current: () => boolean, onDone: (message: string) => void) {
  const { t } = useI18n()
  const pending = useRef<{ provider: SignInProvider; id: string; button: HTMLButtonElement } | null>(null)
  useLayoutEffect(() => {
    const target = pending.current
    if (!target || !identities || identities.some(identity => identity.id === target.id)) return
    pending.current = null
    if (!current() || (document.activeElement !== document.body && document.activeElement !== target.button)) return
    const next = document.querySelector<HTMLButtonElement>(`button[data-sign-in-provider="${target.provider}"]`) ?? document.querySelector<HTMLButtonElement>("#own-password-toggle")
    next?.focus()
  })
  return (provider: SignInProvider, id: string, button: HTMLButtonElement | null) => {
    if (!current()) return
    if (button && document.activeElement === button) pending.current = { provider, id, button }
    onDone(t("settings.signIn.removed", { provider: t(SIGN_IN_NAMES[provider]) }))
  }
}
