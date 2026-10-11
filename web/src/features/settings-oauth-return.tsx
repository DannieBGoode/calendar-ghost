import { ChevronDown, Info, ShieldAlert } from "lucide-react"
import { useId, useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useI18n } from "@/i18n/provider"
import { codeTag, rich } from "@/i18n/rich"
import type { CalendarProvider } from "@/lib/api"
import { oauthReturnAtCurrentOrigin } from "@/lib/oauth-redirect"
import { accountNoun, providerDisplayName } from "@/lib/providers"
import { type OAuthReturn, useOAuthReturn } from "@/lib/use-oauth-return"
import { cn } from "@/lib/utils"

/** The step that finishes a connection a provider returned elsewhere; shown only while it can. */
export function OAuthReturnStep({ help }: { help: OAuthReturn }) {
  const i18n = useI18n()
  const { t } = i18n
  const headingId = useId()
  if (!help.mismatch || !help.awaiting) return null
  const { provider, redirectOrigin } = help.mismatch
  const names = { account: accountNoun(i18n, provider.kind, [provider]), provider: providerDisplayName(i18n, provider.kind, [provider]) }
  return (
    <section className="oauth-feedback oauth-feedback-warning oauth-return" aria-labelledby={headingId}>
      <ShieldAlert aria-hidden="true" />
      <div>
        <h3 id={headingId}>{t("settings.oauthReturn.step.title", names)}</h3>
        <p>{rich(t("settings.oauthReturn.step.body", { ...names, origin: redirectOrigin }), { code: codeTag })}</p>
        <OAuthReturnForm redirectUri={help.mismatch.redirectUri} provider={names.provider} />
      </div>
      <Button variant="ghost" onClick={help.dismiss}>
        {t("settings.oauthReturn.step.dismiss")}
      </Button>
    </section>
  )
}

/** A quiet note that a provider returns elsewhere, with the way to finish and the permanent fix. */
export function OAuthReturnNote({ help, className }: { help: OAuthReturn; className?: string }) {
  const i18n = useI18n()
  const { t } = i18n
  if (!help.mismatch || help.awaiting) return null
  const origin = help.mismatch.redirectOrigin
  const provider = providerDisplayName(i18n, help.mismatch.provider.kind, [help.mismatch.provider])
  return (
    <details className={cn("inline-help", className)}>
      <summary>
        <Info aria-hidden="true" />
        <span>{rich(t("settings.oauthReturn.note.summary", { origin, provider }), { code: codeTag })}</span>
        <ChevronDown className="inline-help-chevron" aria-hidden="true" />
      </summary>
      <div className="inline-help-body">
        <p>{t("settings.oauthReturn.note.body")}</p>
        <OAuthReturnForm redirectUri={help.mismatch.redirectUri} provider={provider} />
        <p>{rich(t("settings.oauthReturn.note.fix", { origin, provider }), { code: codeTag })}</p>
      </div>
    </details>
  )
}

export function OAuthReturnHelp({ providers }: { providers: readonly CalendarProvider[] }) {
  const help = useOAuthReturn(providers)
  return (
    <>
      <OAuthReturnStep help={help} />
      <OAuthReturnNote help={help} />
    </>
  )
}

function OAuthReturnForm({ redirectUri, provider }: { redirectUri: string; provider: string }) {
  const { t } = useI18n()
  const fieldId = useId()
  const [pasted, setPasted] = useState("")
  const [invalid, setInvalid] = useState(false)
  return (
    <form
      className="oauth-return-form"
      onSubmit={(event) => {
        event.preventDefault()
        const target = oauthReturnAtCurrentOrigin(pasted, redirectUri, window.location.origin)
        setInvalid(target === null)
        if (target) window.location.assign(target)
      }}
    >
      <Label htmlFor={fieldId}>{t("settings.oauthReturn.form.label", { provider })}</Label>
      <div className="oauth-return-row">
        <Input
          id={fieldId}
          value={pasted}
          onChange={(event) => {
            setPasted(event.target.value)
            setInvalid(false)
          }}
          placeholder={t("settings.oauthReturn.form.placeholder", { redirectUri })}
          aria-invalid={invalid}
          aria-describedby={invalid ? `${fieldId}-error` : undefined}
          autoComplete="off"
          spellCheck={false}
          required
        />
        <Button type="submit" variant="outline">
          {t("settings.oauthReturn.form.submit")}
        </Button>
      </div>
      {invalid && (
        <p id={`${fieldId}-error`} className="field-error" role="alert">
          {rich(t("settings.oauthReturn.form.invalid", { provider, start: `${redirectUri}?` }), { code: codeTag })}
        </p>
      )}
    </form>
  )
}
