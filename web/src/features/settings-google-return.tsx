import { ChevronDown, Info, ShieldAlert } from "lucide-react"
import { useId, useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { oauthReturnAtCurrentOrigin } from "@/lib/oauth-redirect"
import { type GoogleReturn, useGoogleReturn } from "@/lib/use-google-return"
import { cn } from "@/lib/utils"

/** The step that finishes a connection Google returned elsewhere; shown only while it can. */
export function GoogleReturnStep({ help }: { help: GoogleReturn }) {
  const headingId = useId()
  if (!help.mismatch || !help.awaiting) return null
  return (
    <section className="oauth-feedback oauth-feedback-warning oauth-return" aria-labelledby={headingId}>
      <ShieldAlert aria-hidden="true" />
      <div>
        <h3 id={headingId}>Finish connecting your Google account</h3>
        <p>
          Google sends your browser to <code>{help.mismatch.redirectOrigin}</code> after you approve
          access. If that page did not load, copy its whole address from the address bar and paste it
          here. It works once, for 10 minutes.
        </p>
        <OAuthReturnForm redirectUri={help.mismatch.redirectUri} />
      </div>
      <Button variant="ghost" onClick={help.dismiss}>
        Dismiss
      </Button>
    </section>
  )
}

/** A quiet note that Google returns elsewhere, with the way to finish and the permanent fix. */
export function GoogleReturnNote({ help, className }: { help: GoogleReturn; className?: string }) {
  if (!help.mismatch || help.awaiting) return null
  return (
    <details className={cn("inline-help", className)}>
      <summary>
        <Info aria-hidden="true" />
        <span>
          Google returns to <code>{help.mismatch.redirectOrigin}</code>, not this address
        </span>
        <ChevronDown className="inline-help-chevron" aria-hidden="true" />
      </summary>
      <div className="inline-help-body">
        <p>
          If its page does not load after you approve access, copy the whole address from the address
          bar and paste it here within 10 minutes to finish connecting.
        </p>
        <OAuthReturnForm redirectUri={help.mismatch.redirectUri} />
        <p>
          To stop this, set <code>CALENDAR_SYNC_GOOGLE_REDIRECT_URI</code> to an HTTPS address of this
          installation, for example with Tailscale Serve, and register it on your Google OAuth client.
          Opening Calendar Ghost at <code>{help.mismatch.redirectOrigin}</code>, for example through an
          SSH tunnel, also works.
        </p>
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
      <Label htmlFor={fieldId}>Address Google returned to</Label>
      <div className="oauth-return-row">
        <Input
          id={fieldId}
          value={pasted}
          onChange={(event) => {
            setPasted(event.target.value)
            setInvalid(false)
          }}
          placeholder={`${redirectUri}?state=…`}
          aria-invalid={invalid}
          aria-describedby={invalid ? `${fieldId}-error` : undefined}
          autoComplete="off"
          spellCheck={false}
          required
        />
        <Button type="submit" variant="outline">
          Finish connecting
        </Button>
      </div>
      {invalid && (
        <p id={`${fieldId}-error`} className="field-error" role="alert">
          That is not the address Google returned to. Copy the whole address, starting with{" "}
          <code>{redirectUri}?</code>
        </p>
      )}
    </form>
  )
}
