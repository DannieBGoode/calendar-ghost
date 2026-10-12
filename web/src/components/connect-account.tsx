import { Plus } from "lucide-react"

import { OverflowMenu } from "@/components/overflow-menu"
import { ProviderMark } from "@/components/provider-mark"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/i18n/provider"
import type { CalendarProvider } from "@/lib/api"
import { recordAuthorizationStart } from "@/lib/oauth-redirect"
import { accountNoun, connectUrl, providerDisplayName } from "@/lib/providers"

/**
 * The one action that adds a calendar account: a button for the only configured provider, or a
 * menu of providers when there are several, so the page never shows one equal button per provider.
 * `primary` only where connecting is the next step (DESIGN.md, Buttons).
 */
export function ConnectAccount({ providers, primary }: { providers: readonly CalendarProvider[]; primary: boolean }) {
  const i18n = useI18n()
  const variant = primary ? "default" : "outline"
  const [only] = providers
  if (providers.length === 1 && only) {
    return (
      <Button variant={variant} asChild>
        <a href={connectUrl(only)} onClick={() => recordAuthorizationStart(only.kind)}>
          <ProviderMark provider={only.kind} fallback={<Plus aria-hidden="true" />} />
          {i18n.t("common.connectAccount.one", { account: accountNoun(i18n, only.kind, providers) })}
        </a>
      </Button>
    )
  }
  return (
    <OverflowMenu
      label={i18n.t("common.connectAccount.menu")}
      trigger={{ icon: <Plus aria-hidden="true" />, variant }}
      items={providers.map((provider) => ({
        id: provider.kind,
        label: accountNoun(i18n, provider.kind, providers),
        description: i18n.t("common.connectAccount.signIn", {
          provider: providerDisplayName(i18n, provider.kind, providers),
        }),
        icon: <ProviderMark provider={provider.kind} fallback={<Plus aria-hidden="true" />} />,
        href: connectUrl(provider),
        onSelect: () => recordAuthorizationStart(provider.kind),
      }))}
    />
  )
}
