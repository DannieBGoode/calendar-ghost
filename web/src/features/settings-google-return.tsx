import { ChevronDown, Info, ShieldAlert } from "lucide-react"
import { useId, useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useI18n } from "@/i18n/provider"
import { codeTag, rich } from "@/i18n/rich"
import { oauthReturnAtCurrentOrigin } from "@/lib/oauth-redirect"
import { type GoogleReturn, useGoogleReturn } from "@/lib/use-google-return"
import { cn } from "@/lib/utils"

/** The step that finishes a connection Google returned elsewhere; shown only while it can. */
export function GoogleReturnStep({ help }: { help: GoogleReturn }) {
  const { t } = useI18n()
  const headingId = useId()
  if (!help.mismatch || !help.awaiting) return null
  return (
    <section className="oauth-feedback oauth-feedback-warning oauth-return" aria-labelledby={headingId}>
      <ShieldAlert aria-hidden="true" />
      <div>
        <h3 id={headingId}>{t("settings.googleReturn.step.title")}</h3>
        <p>{rich(t("settings.googleReturn.step.body", { origin: help.mismatch.redirectOrigin }), { code: codeTag })}</p>
        <OAuthReturnForm redirectUri={help.mismatch.redirectUri} />
      </div>
      <Button variant="ghost" onClick={help.dismiss}>
        {t("settings.googleReturn.step.dismiss")}
      </Button>
    </section>
  )
}

/** A quiet note that Google returns elsewhere, with the way to finish and the permanent fix. */
export function GoogleReturnNote({ help, className }: { help: GoogleReturn; className?: string }) {
  const { t } = useI18n()
  if (!help.mismatch || help.awaiting) return null
  const origin = help.mismatch.redirectOrigin
  return (
    <details className={cn("inline-help", className)}>
      <summary>
        <Info aria-hidden="true" />
        <span>{rich(t("settings.googleReturn.note.summary", { origin }), { code: codeTag })}</span>
        <ChevronDown className="inline-help-chevron" aria-hidden="true" />
      </summary>
      <div className="inline-help-body">
        <p>{t("settings.googleReturn.note.body")}</p>
        <OAuthReturnForm redirectUri={help.mismatch.redirectUri} />
        <p>{rich(t("settings.googleReturn.note.fix", { origin }), { code: codeTag })}</p>
      </div>
    </details>
  )
}

export function GoogleReturnHelp({ redirectUri }: { redirectUri: string | null }) {
  const help = useGoogleReturn(redirectUri)
  return (
    <>
      <GoogleReturnStep help={help} />
      <GoogleReturnNote help={help} />
    </>
  )
}

function OAuthReturnForm({ redirectUri }: { redirectUri: string }) {
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
      <Label htmlFor={fieldId}>{t("settings.googleReturn.form.label")}</Label>
      <div className="oauth-return-row">
        <Input
          id={fieldId}
          value={pasted}
          onChange={(event) => {
            setPasted(event.target.value)
            setInvalid(false)
          }}
          placeholder={t("settings.googleReturn.form.placeholder", { redirectUri })}
          aria-invalid={invalid}
          aria-describedby={invalid ? `${fieldId}-error` : undefined}
          autoComplete="off"
          spellCheck={false}
          required
        />
        <Button type="submit" variant="outline">
          {t("settings.googleReturn.form.submit")}
        </Button>
      </div>
      {invalid && (
        <p id={`${fieldId}-error`} className="field-error" role="alert">
          {rich(t("settings.googleReturn.form.invalid", { start: `${redirectUri}?` }), { code: codeTag })}
        </p>
      )}
    </form>
  )
}
