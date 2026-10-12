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
import { type OAuthMismatch, type OAuthReturn, useOAuthReturn } from "@/lib/use-oauth-return"
import { cn } from "@/lib/utils"

/** The step that finishes a connection a provider returned elsewhere; shown only while it can. */
export function OAuthReturnStep({ help }: { help: OAuthReturn }) {
  const i18n = useI18n()
  const { t } = i18n
  const headingId = useId()
  const [mismatch] = help.mismatches
  if (!mismatch || !help.awaiting) return null
  const { provider, redirectOrigin } = mismatch
  const names = { account: accountNoun(i18n, provider.kind, [provider]), provider: providerDisplayName(i18n, provider.kind, [provider]) }
  return (
    <section className="oauth-feedback oauth-feedback-warning oauth-return" aria-labelledby={headingId}>
      <ShieldAlert aria-hidden="true" />
      <div>
        <h3 id={headingId}>{t("settings.oauthReturn.step.title", names)}</h3>
        <p>{rich(t("settings.oauthReturn.step.body", { ...names, origin: redirectOrigin }), { code: codeTag })}</p>
        <OAuthReturnForm mismatches={[mismatch]} />
      </div>
      <Button variant="ghost" onClick={help.dismiss}>
        {t("settings.oauthReturn.step.dismiss")}
      </Button>
    </section>
  )
}

/**
 * One quiet note for every provider that returns somewhere other than this address: where each
 * returns, one field that finishes any of them, and the permanent fix.
 */
export function OAuthReturnNote({ help, className }: { help: OAuthReturn; className?: string }) {
  const i18n = useI18n()
  const { t } = i18n
  const { mismatches } = help
  const [first] = mismatches
  if (help.awaiting || !first) return null
  const named = mismatches.map((mismatch) => ({
    mismatch,
    name: providerDisplayName(i18n, mismatch.provider.kind, [mismatch.provider]),
  }))
  // One installation usually answers at one address, so providers that disagree deserve a look.
  const apart = mismatches.some((mismatch) => mismatch.redirectOrigin !== first.redirectOrigin)
  const words = {
    origin: first.redirectOrigin,
    count: mismatches.length,
    provider: i18n.format.list(named.map(({ name }) => name)),
  }
  return (
    <details className={cn("inline-help", className)}>
      <summary>
        <Info aria-hidden="true" />
        <span>{rich(t(apart ? "settings.oauthReturn.note.summaryApart" : "settings.oauthReturn.note.summary", words), { code: codeTag })}</span>
        <ChevronDown className="inline-help-chevron" aria-hidden="true" />
      </summary>
      <div className="inline-help-body">
        {apart && (
          <ul className="oauth-return-origins">
            {named.map(({ mismatch, name }) => (
              <li key={mismatch.provider.kind}>
                {rich(t("settings.oauthReturn.note.origin", { provider: name, origin: mismatch.redirectOrigin }), { code: codeTag })}
              </li>
            ))}
          </ul>
        )}
        <p>{t("settings.oauthReturn.note.body")}</p>
        <OAuthReturnForm mismatches={mismatches} />
        <p>{rich(t(apart ? "settings.oauthReturn.note.fixApart" : "settings.oauthReturn.note.fix", words), { code: codeTag })}</p>
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

/** The field that finishes a connection from the address a provider returned to; the address names its provider. */
function OAuthReturnForm({ mismatches }: { mismatches: readonly OAuthMismatch[] }) {
  const i18n = useI18n()
  const { t } = i18n
  const fieldId = useId()
  const [pasted, setPasted] = useState("")
  const [invalid, setInvalid] = useState(false)
  const [only] = mismatches
  const words = {
    count: mismatches.length,
    provider: only ? providerDisplayName(i18n, only.provider.kind, [only.provider]) : "",
    start: `${only?.redirectUri ?? ""}?`,
  }
  return (
    <form
      className="oauth-return-form"
      onSubmit={(event) => {
        event.preventDefault()
        const target = firstReturn(pasted, mismatches, window.location.origin)
        setInvalid(target === null)
        if (target) window.location.assign(target)
      }}
    >
      <Label htmlFor={fieldId}>{t("settings.oauthReturn.form.label", words)}</Label>
      <div className="oauth-return-row">
        <Input
          id={fieldId}
          value={pasted}
          onChange={(event) => {
            setPasted(event.target.value)
            setInvalid(false)
          }}
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
          {rich(t("settings.oauthReturn.form.invalid", words), { code: codeTag })}
        </p>
      )}
    </form>
  )
}

/** The pasted address moved to this origin, for whichever provider it returned from. */
function firstReturn(pasted: string, mismatches: readonly OAuthMismatch[], currentOrigin: string): string | null {
  for (const { redirectUri } of mismatches) {
    const target = oauthReturnAtCurrentOrigin(pasted, redirectUri, currentOrigin)
    if (target) return target
  }
  return null
}
