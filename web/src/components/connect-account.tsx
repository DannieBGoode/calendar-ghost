import { Plus } from "lucide-react"
import { useId } from "react"

import { OverflowMenu } from "@/components/overflow-menu"
import { ProviderMark } from "@/components/provider-mark"
import { Button } from "@/components/ui/button"
import { YourPlanLink } from "@/components/your-plan-link"
import { useI18n } from "@/i18n/provider"
import type { I18n } from "@/i18n/translator"
import type { CalendarProvider } from "@/lib/api"
import { connectLink } from "@/lib/oauth-redirect"
import { accountNoun, providerDisplayName } from "@/lib/providers"

/**
 * The one action that adds a calendar account: a button for the only configured provider, or a
 * menu of providers when there are several, so the page never shows one equal button per provider.
 * `primary` only where connecting is the next step (DESIGN.md, Buttons). With `disabledReason`,
 * such as the User's plan's account limit, it stays in place but starts nothing, and says why.
 */
export function ConnectAccount({
  providers,
  primary,
  disabledReason,
}: {
  providers: readonly CalendarProvider[]
  primary: boolean
  /** Why no account can be connected now; the server still checks after the provider's consent. */
  disabledReason?: string | undefined
}) {
  const i18n = useI18n()
  const variant = primary ? "default" : "outline"
  const [only] = providers
  if (disabledReason !== undefined) {
    return <UnavailableConnect label={connectLabel(i18n, providers)} variant={variant} reason={disabledReason} />
  }
  if (providers.length === 1 && only) {
    return (
      <Button variant={variant} asChild>
        <a {...connectLink(only)}>
          <ProviderMark provider={only.kind} fallback={<Plus aria-hidden="true" />} />
          {connectLabel(i18n, providers)}
        </a>
      </Button>
    )
  }
  return (
    <OverflowMenu
      label={i18n.t("common.connectAccount.menu")}
      trigger={{ icon: <Plus aria-hidden="true" />, variant }}
      items={providers.map((provider) => {
        const link = connectLink(provider)
        return {
          id: provider.kind,
          label: accountNoun(i18n, provider.kind, providers),
          description: signInHint(i18n, provider, providers),
          icon: <ProviderMark provider={provider.kind} fallback={<Plus aria-hidden="true" />} />,
          href: link.href,
          newTab: link.target === "_blank",
          onSelect: link.onClick,
        }
      })}
    />
  )
}

/** Connect's label: the only provider's account, or the menu that chooses one. */
function connectLabel(i18n: I18n, providers: readonly CalendarProvider[]): string {
  const [only] = providers
  return providers.length === 1 && only
    ? i18n.t("common.connectAccount.one", { account: accountNoun(i18n, only.kind, providers) })
    : i18n.t("common.connectAccount.menu")
}

/**
 * Connect, unavailable: the same label on a button that leads nowhere, never a link to a
 * provider's consent or a menu of them, described by why and a link to Your plan. It stays
 * focusable, so keyboard and screen reader users reach the reason.
 */
function UnavailableConnect({
  label,
  variant,
  reason,
}: {
  label: string
  variant: "default" | "outline"
  reason: string
}) {
  const hint = useId()
  return (
    <div className="heading-action">
      <Button type="button" variant={variant} aria-disabled={true} aria-describedby={hint}>
        <Plus aria-hidden="true" />
        {label}
      </Button>
      <p id={hint} className="action-hint">
        {reason} <YourPlanLink />
      </p>
    </div>
  )
}

/** How to connect an account of the provider, then what is not yet verified for it, if anything. */
function signInHint(i18n: I18n, provider: CalendarProvider, providers: readonly CalendarProvider[]): string {
  const signIn = i18n.t("common.connectAccount.signIn", {
    provider: providerDisplayName(i18n, provider.kind, providers),
  })
  const note = `common.connectAccount.note.${provider.kind}`
  return i18n.has(note) ? `${signIn} ${i18n.t(note)}` : signIn
}
