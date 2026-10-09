import { Check, Copy } from "lucide-react"
import { useEffect, useRef } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useI18n } from "@/i18n/provider"
import { copyToken } from "@/lib/integrations"
import { useCopyState } from "@/lib/use-copy-state"

/**
 * A link shown once, such as an Invitation or a Password Reset Link, for the administrator to
 * pass on. Focus moves to it when it appears; the link is never announced, only shown.
 */
export function LinkReveal({
  title,
  body,
  label,
  link,
  onDone,
}: {
  title: string
  body: string
  label: string
  link: string
  onDone: () => void
}) {
  const { t } = useI18n()
  const heading = useRef<HTMLHeadingElement>(null)
  const [copyState, setCopyState] = useCopyState()
  useEffect(() => {
    heading.current?.focus()
  }, [link])

  return (
    <div className="setting-row token-reveal link-reveal">
      <div className="token-reveal-copy">
        <h3 ref={heading} tabIndex={-1}>
          {title}
        </h3>
        <p>{body}</p>
        <div className="token-field">
          <Input readOnly value={link} aria-label={label} onFocus={(event) => event.currentTarget.select()} />
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              void copyToken(link, navigator.clipboard).then(setCopyState)
            }}
          >
            {copyState === "copied" ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
            {copyState === "copied" ? t("settings.links.copied") : t("settings.links.copy")}
          </Button>
        </div>
        {copyState === "unavailable" && <p>{t("settings.links.copyUnavailable")}</p>}
      </div>
      <Button type="button" variant="ghost" onClick={onDone}>
        {t("settings.links.done")}
      </Button>
    </div>
  )
}
