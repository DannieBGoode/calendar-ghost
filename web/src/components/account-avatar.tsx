import { useState } from "react"

import { ProviderMark } from "@/components/provider-mark"
import { useI18n } from "@/i18n/provider"
import { accountInitials } from "@/lib/account-avatar"
import { accountNoun } from "@/lib/providers"
import { cn } from "@/lib/utils"

export function AccountAvatar({
  displayName,
  email,
  avatarUrl,
  provider,
  compact = false,
}: {
  displayName: string
  email: string
  avatarUrl: string | null | undefined
  /** The account's Provider Kind, whose mark sits on the avatar's corner; the text beside it names it too. */
  provider?: string | null | undefined
  compact?: boolean
}) {
  const i18n = useI18n()
  const { locale } = i18n
  const [failedUrl, setFailedUrl] = useState<string | null>(null)
  const photo = avatarUrl && avatarUrl !== failedUrl ? avatarUrl : null
  return (
    <span
      className={cn("account-mark", compact && "account-mark-compact")}
      title={provider ? accountNoun(i18n, provider) : undefined}
      aria-hidden="true"
    >
      {photo ? (
        <img
          src={photo}
          alt=""
          referrerPolicy="no-referrer"
          decoding="async"
          onError={() => setFailedUrl(photo)}
        />
      ) : (
        <span>{accountInitials(displayName, email, locale)}</span>
      )}
      <ProviderMark provider={provider} className="account-provider-mark" />
    </span>
  )
}
