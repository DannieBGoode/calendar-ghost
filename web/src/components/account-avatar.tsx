import { useState } from "react"

import { accountInitials } from "@/lib/account-avatar"
import { cn } from "@/lib/utils"

export function AccountAvatar({
  displayName,
  email,
  avatarUrl,
  compact = false,
}: {
  displayName: string
  email: string
  avatarUrl: string | null | undefined
  compact?: boolean
}) {
  const [failedUrl, setFailedUrl] = useState<string | null>(null)
  const photo = avatarUrl && avatarUrl !== failedUrl ? avatarUrl : null
  return (
    <span className={cn("account-mark", compact && "account-mark-compact")} aria-hidden="true">
      {photo ? (
        <img
          src={photo}
          alt=""
          referrerPolicy="no-referrer"
          decoding="async"
          onError={() => setFailedUrl(photo)}
        />
      ) : (
        accountInitials(displayName, email)
      )}
    </span>
  )
}
