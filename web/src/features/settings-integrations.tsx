import { Check, ChevronDown, Copy, Info, KeyRound } from "lucide-react"
import { Fragment, useEffect, useRef, useState, type RefObject } from "react"

import { DestructiveConfirmation } from "@/components/destructive-confirmation"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import type { IntegrationToken, IssuedIntegrationToken } from "@/lib/api"
import { copyToken, integrationExamples, integrationSummary, needsTransportNote, tokenUsage } from "@/lib/integrations"
import { useIntegrationTokens, type CopyState, type IntegrationTokens } from "@/lib/use-integration-tokens"
import { useNow } from "@/lib/use-now"

/**
 * Integration Tokens as one Settings group. It stays collapsed to a summary row, as Connected
 * accounts does, because most administrators never need it.
 */
export function IntegrationsSection() {
  const now = useNow()
  const integrations = useIntegrationTokens()
  const [open, setOpen] = useState(false)
  const { tokens, summaryButton, message } = integrations

  return (
    <section className="settings-section" aria-labelledby="integrations-title">
      <div className="section-heading">
        <div>
          <h2 id="integrations-title">Integrations</h2>
          <p>
            Optional. Tokens let monitors, dashboards, and AI assistants read whether
            synchronization is healthy. They cannot change anything.
          </p>
        </div>
      </div>
      {tokens.isPending && <Skeleton className="h-16 w-full" />}
      {tokens.error && (
        <div className="inline-error integration-load-error" role="alert">
          <span>Integration tokens could not load.</span>
          <Button type="button" variant="outline" onClick={() => void tokens.refetch()}>
            Try again
          </Button>
        </div>
      )}
      {tokens.data && (
        <div className="settings-group">
          <button
            ref={summaryButton}
            type="button"
            className="group-summary"
            aria-expanded={open}
            aria-controls={open ? "integration-body" : undefined}
            onClick={() => setOpen(!open)}
          >
            <KeyRound className="group-summary-icon" aria-hidden="true" />
            <span className="account-summary-copy">
              <span className="account-summary-status">{integrationSummary(tokens.data, now)}</span>
              <span className="account-summary-emails">For monitors, dashboards, and AI assistants</span>
            </span>
            <span className="account-summary-toggle">
              {open ? "Hide" : "Show"}
              <span className="sr-only"> integrations</span>
              <ChevronDown aria-hidden="true" />
            </span>
          </button>
          {open && <IntegrationsBody tokens={tokens.data} now={now} integrations={integrations} />}
          {open && <IntegrationsFooter origin={window.location.origin} />}
        </div>
      )}
      {message && <p role="status">{message}</p>}
    </section>
  )
}

function IntegrationsBody({
  tokens,
  now,
  integrations,
}: {
  tokens: IntegrationToken[]
  now: number
  integrations: IntegrationTokens
}) {
  const nameInput = useRef<HTMLInputElement>(null)
  const { issued, copyState, setCopyState, finishReveal } = integrations
  const active = tokens.filter((token) => !token.revoked_at)
  const revoked = tokens.filter((token) => token.revoked_at)

  return (
    <div className="group-body" id="integration-body">
      <IssueTokenForm integrations={integrations} nameInput={nameInput} />
      {issued && (
        <TokenReveal
          issued={issued}
          copyState={copyState}
          onCopied={setCopyState}
          onDone={() => {
            finishReveal()
            nameInput.current?.focus()
          }}
        />
      )}
      {active.map((token) => (
        <ActiveToken key={token.id} token={token} now={now} integrations={integrations} />
      ))}
      {revoked.length > 0 && <RevokedTokens revoked={revoked} now={now} />}
    </div>
  )
}

function IssueTokenForm({
  integrations,
  nameInput,
}: {
  integrations: IntegrationTokens
  nameInput: RefObject<HTMLInputElement | null>
}) {
  const { name, setName, issue } = integrations
  return (
    <form
      className="setting-row integration-issue"
      onSubmit={(event) => {
        event.preventDefault()
        issue.mutate()
      }}
    >
      <div className="integration-issue-field">
        <Label htmlFor="integration-name">Issue a token</Label>
        <p id="integration-name-hint">Name the tool that will use it.</p>
        <Input
          ref={nameInput}
          id="integration-name"
          value={name}
          maxLength={80}
          placeholder="For example, Uptime Kuma"
          aria-describedby="integration-name-hint"
          onChange={(event) => setName(event.target.value)}
        />
        {issue.error && (
          <p className="field-error" role="alert">
            {issue.error.message}
          </p>
        )}
      </div>
      <Button type="submit" disabled={!name.trim() || issue.isPending}>
        {issue.isPending ? "Issuing…" : "Issue token"}
      </Button>
    </form>
  )
}

function TokenReveal({
  issued,
  copyState,
  onCopied,
  onDone,
}: {
  issued: IssuedIntegrationToken
  copyState: CopyState
  onCopied: (state: CopyState) => void
  onDone: () => void
}) {
  const revealHeading = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    revealHeading.current?.focus()
  }, [issued])

  return (
    <div className="setting-row token-reveal">
      <div className="token-reveal-copy">
        <h3 ref={revealHeading} tabIndex={-1}>
          Copy the token for {issued.name} now
        </h3>
        <p>It is shown only once. Store it in your password manager or the tool that uses it.</p>
        <div className="token-field">
          <Input
            readOnly
            value={issued.token}
            aria-label={`Token for ${issued.name}`}
            onFocus={(event) => event.currentTarget.select()}
          />
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              void copyToken(issued.token, navigator.clipboard).then(onCopied)
            }}
          >
            {copyState === "copied" ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
            {copyState === "copied" ? "Copied" : "Copy token"}
          </Button>
        </div>
        {copyState === "unavailable" && <p>Select the token and copy it.</p>}
      </div>
      <Button type="button" variant="ghost" onClick={onDone}>
        Done
      </Button>
    </div>
  )
}

function ActiveToken({
  token,
  now,
  integrations,
}: {
  token: IntegrationToken
  now: number
  integrations: IntegrationTokens
}) {
  const trigger = useRef<HTMLButtonElement>(null)
  const { revoking, setRevoking, revoke } = integrations
  return (
    <Fragment>
      <div className="setting-row">
        <div>
          <h3>{token.name}</h3>
          <p>{tokenUsage(token, now)}</p>
        </div>
        <Button
          ref={trigger}
          type="button"
          variant="outline"
          aria-expanded={revoking === token.id}
          aria-controls={`revoke-${token.id}`}
          onClick={() => {
            revoke.reset()
            setRevoking(token.id)
          }}
        >
          Revoke
        </Button>
      </div>
      {revoking === token.id && (
        <>
          <DestructiveConfirmation
            id={`revoke-${token.id}`}
            title={`Revoke ${token.name}?`}
            body="Anything that uses this token loses access right away. This cannot be undone."
            cancelLabel="Keep token"
            confirmLabel="Revoke token"
            pendingLabel="Revoking…"
            pending={revoke.isPending}
            confirmIcon={null}
            onConfirm={() => revoke.mutate(token)}
            onCancel={() => {
              setRevoking(null)
              trigger.current?.focus()
            }}
          />
          {revoke.error && (
            <p className="field-error" role="alert">
              {revoke.error.message}
            </p>
          )}
        </>
      )}
    </Fragment>
  )
}

function RevokedTokens({ revoked, now }: { revoked: IntegrationToken[]; now: number }) {
  return (
    <details className="inline-help setting-help revoked-tokens">
      <summary>
        <span>
          {revoked.length} revoked {revoked.length === 1 ? "token" : "tokens"}
        </span>
        <ChevronDown className="inline-help-chevron" aria-hidden="true" />
      </summary>
      <ul className="inline-help-body">
        {revoked.map((token) => (
          <li key={token.id}>
            {token.name} · {tokenUsage(token, now)}
          </li>
        ))}
      </ul>
    </details>
  )
}

function IntegrationsFooter({ origin }: { origin: string }) {
  return (
    <div className="group-footer">
      {needsTransportNote(origin) && (
        <details className="inline-help">
          <summary>
            <Info aria-hidden="true" />
            <span>This address uses plain HTTP</span>
            <ChevronDown className="inline-help-chevron" aria-hidden="true" />
          </summary>
          <div className="inline-help-body">
            <p>
              A token sent to this address crosses the internet unencrypted. Serve Calendar Ghost
              over HTTPS, for example with Tailscale Serve or a reverse proxy, before you use
              tokens from outside your home network.
            </p>
          </div>
        </details>
      )}
      <details className="inline-help">
        <summary>
          <Info aria-hidden="true" />
          <span>Examples for monitors and AI assistants</span>
          <ChevronDown className="inline-help-chevron" aria-hidden="true" />
        </summary>
        <div className="inline-help-body integration-examples">
          <p>Replace the token placeholder in each example with the token you copied.</p>
          {integrationExamples(origin).map((example) => (
            <div key={example.title}>
              <h3>{example.title}</h3>
              <p>{example.description}</p>
              <pre>
                <code>{example.code}</code>
              </pre>
            </div>
          ))}
        </div>
      </details>
    </div>
  )
}
