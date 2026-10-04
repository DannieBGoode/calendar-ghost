import { Check, ChevronDown, Copy, Info, KeyRound } from "lucide-react"
import { Fragment, useEffect, useRef, useState, type RefObject } from "react"

import { DestructiveConfirmation } from "@/components/destructive-confirmation"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import type { IntegrationToken, IssuedIntegrationToken } from "@/lib/api"
import { copyToken, integrationExamples, integrationSummary, needsTransportNote, tokenUsage } from "@/lib/integrations"
import { useIntegrationTokens, type CopyState, type IntegrationTokens } from "@/lib/use-integration-tokens"
import { useNow } from "@/lib/use-now"

/**
 * Integration Tokens as one Settings group. It stays collapsed to a summary row, as Connected
 * accounts does, because most administrators never need it.
 */
export function IntegrationsSection() {
  const i18n = useI18n()
  const { t } = i18n
  const now = useNow()
  const integrations = useIntegrationTokens()
  const [open, setOpen] = useState(false)
  const { tokens, summaryButton, message } = integrations

  return (
    <section className="settings-section" aria-labelledby="integrations-title">
      <div className="section-heading">
        <div>
          <h2 id="integrations-title">{t("settings.integrations.title")}</h2>
          <p>{t("settings.integrations.intro")}</p>
        </div>
      </div>
      {tokens.isPending && <Skeleton className="h-16 w-full" />}
      {tokens.error && (
        <div className="inline-error integration-load-error" role="alert">
          <span>{t("settings.integrations.loadError")}</span>
          <Button type="button" variant="outline" onClick={() => void tokens.refetch()}>
            {t("settings.integrations.tryAgain")}
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
              <span className="account-summary-status">{integrationSummary(i18n, tokens.data, now)}</span>
              <span className="account-summary-emails">{t("settings.integrations.summaryDetail")}</span>
            </span>
            <span className="account-summary-toggle">
              <span aria-hidden="true">
                {open ? t("settings.integrations.toggle.hide") : t("settings.integrations.toggle.show")}
              </span>
              <span className="sr-only">
                {open ? t("settings.integrations.toggle.hideIntegrations") : t("settings.integrations.toggle.showIntegrations")}
              </span>
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
  const i18n = useI18n()
  const { t } = i18n
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
        <Label htmlFor="integration-name">{t("settings.integrations.issue.label")}</Label>
        <p id="integration-name-hint">{t("settings.integrations.issue.hint")}</p>
        <Input
          ref={nameInput}
          id="integration-name"
          value={name}
          maxLength={80}
          placeholder={t("settings.integrations.issue.placeholder")}
          aria-describedby="integration-name-hint"
          onChange={(event) => setName(event.target.value)}
        />
        {issue.error && (
          <p className="field-error" role="alert">
            {apiErrorMessage(i18n, issue.error)}
          </p>
        )}
      </div>
      <Button type="submit" disabled={!name.trim() || issue.isPending}>
        {issue.isPending ? t("settings.integrations.issue.pending") : t("settings.integrations.issue.submit")}
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
  const { t } = useI18n()
  const revealHeading = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    revealHeading.current?.focus()
  }, [issued])

  return (
    <div className="setting-row token-reveal">
      <div className="token-reveal-copy">
        <h3 ref={revealHeading} tabIndex={-1}>
          {t("settings.integrations.reveal.title", { name: issued.name })}
        </h3>
        <p>{t("settings.integrations.reveal.body")}</p>
        <div className="token-field">
          <Input
            readOnly
            value={issued.token}
            aria-label={t("settings.integrations.reveal.tokenLabel", { name: issued.name })}
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
            {copyState === "copied" ? t("settings.integrations.reveal.copied") : t("settings.integrations.reveal.copy")}
          </Button>
        </div>
        {copyState === "unavailable" && <p>{t("settings.integrations.reveal.copyUnavailable")}</p>}
      </div>
      <Button type="button" variant="ghost" onClick={onDone}>
        {t("settings.integrations.reveal.done")}
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
  const i18n = useI18n()
  const { t } = i18n
  const trigger = useRef<HTMLButtonElement>(null)
  const { revoking, setRevoking, revoke } = integrations
  return (
    <Fragment>
      <div className="setting-row">
        <div>
          <h3>{token.name}</h3>
          <p>{tokenUsage(i18n, token, now)}</p>
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
          {t("settings.integrations.revoke.action")}
        </Button>
      </div>
      {revoking === token.id && (
        <>
          <DestructiveConfirmation
            id={`revoke-${token.id}`}
            title={t("settings.integrations.revoke.title", { name: token.name })}
            body={t("settings.integrations.revoke.body")}
            cancelLabel={t("settings.integrations.revoke.keep")}
            confirmLabel={t("settings.integrations.revoke.confirm")}
            pendingLabel={t("settings.integrations.revoke.pending")}
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
              {apiErrorMessage(i18n, revoke.error)}
            </p>
          )}
        </>
      )}
    </Fragment>
  )
}

function RevokedTokens({ revoked, now }: { revoked: IntegrationToken[]; now: number }) {
  const i18n = useI18n()
  const { t } = i18n
  return (
    <details className="inline-help setting-help revoked-tokens">
      <summary>
        <span>{t("settings.integrations.revokedCount", { count: revoked.length })}</span>
        <ChevronDown className="inline-help-chevron" aria-hidden="true" />
      </summary>
      <ul className="inline-help-body">
        {revoked.map((token) => (
          <li key={token.id}>
            {t("settings.integrations.revokedItem", { name: token.name, usage: tokenUsage(i18n, token, now) })}
          </li>
        ))}
      </ul>
    </details>
  )
}

function IntegrationsFooter({ origin }: { origin: string }) {
  const i18n = useI18n()
  const { t } = i18n
  return (
    <div className="group-footer">
      {needsTransportNote(origin) && (
        <details className="inline-help">
          <summary>
            <Info aria-hidden="true" />
            <span>{t("settings.integrations.transport.summary")}</span>
            <ChevronDown className="inline-help-chevron" aria-hidden="true" />
          </summary>
          <div className="inline-help-body">
            <p>{t("settings.integrations.transport.body")}</p>
          </div>
        </details>
      )}
      <details className="inline-help">
        <summary>
          <Info aria-hidden="true" />
          <span>{t("settings.integrations.examples.summary")}</span>
          <ChevronDown className="inline-help-chevron" aria-hidden="true" />
        </summary>
        <div className="inline-help-body integration-examples">
          <p>{t("settings.integrations.examples.intro")}</p>
          {integrationExamples(i18n, origin).map((example) => (
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
