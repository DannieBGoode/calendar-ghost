import { useMutation, useQuery } from "@tanstack/react-query"
import { useRef, useState, type RefObject, type SyntheticEvent } from "react"

import { DestructiveConfirmation } from "@/components/destructive-confirmation"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { NativeSelect } from "@/components/ui/native-select"
import { ProjectionChoice } from "@/features/projection-choice"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import {
  api,
  type ConnectedAccount,
  type DiscoveredCalendar,
  type ProjectionHandling,
  type RuleDetail,
} from "@/lib/api"
import { removalConsequence, removalResultSentences, replacementConfirmLabel } from "@/lib/rule-change"
import { endpointDraft, replacementReadiness, type EndpointDraft } from "@/lib/rule-replacement"
import { useDisclosureFocus } from "@/lib/use-disclosure-focus"
import { useRuleExit, useRuleInvalidation } from "@/lib/use-rule-refresh"
import { writableCalendars } from "@/lib/writable-calendars"

/** Exported so rendered tests can exercise the draft without the full rule page. */
export function CalendarReplacement({
  detail,
  accounts,
  destinationName,
  destinationConnected,
  onReplaced,
}: {
  detail: RuleDetail
  accounts: ConnectedAccount[]
  destinationName: string
  destinationConnected: boolean
  onReplaced: (ruleId: string, notice: string) => void
}) {
  const i18n = useI18n()
  const { t } = i18n
  const invalidate = useRuleInvalidation(detail.id)
  const leave = useRuleExit(detail.id)
  const connected = accounts.filter((account) => account.state === "connected")
  const toggle = useRef<HTMLButtonElement>(null)
  const firstField = useRef<HTMLSelectElement>(null)
  const [open, setOpen] = useState(false)
  useDisclosureFocus(open, firstField, toggle)
  // Only the administrator's edits are state; an untouched field follows the rule as it loads.
  const [edits, setEdits] = useState<Partial<EndpointDraft>>({})
  const draft = endpointDraft(detail, edits)
  const [handling, setHandling] = useState<ProjectionHandling>("delete")
  const effective: ProjectionHandling = destinationConnected ? handling : "detach"
  const sourceCalendars = useQuery({
    queryKey: ["calendars", draft.sourceAccount],
    queryFn: () => api.calendars(draft.sourceAccount),
    staleTime: 5 * 60 * 1000,
    enabled: open && connected.some((account) => account.id === draft.sourceAccount),
  })
  const destinationCalendars = useQuery({
    queryKey: ["calendars", draft.destinationAccount],
    queryFn: () => api.calendars(draft.destinationAccount),
    staleTime: 5 * 60 * 1000,
    enabled: open && connected.some((account) => account.id === draft.destinationAccount),
  })
  const replace = useMutation({
    mutationFn: () =>
      api.replaceRuleCalendars(detail.id, {
        source: { connected_account_id: draft.sourceAccount, calendar_id: draft.sourceCalendar },
        destination: { connected_account_id: draft.destinationAccount, calendar_id: draft.destinationCalendar },
        projections: effective,
      }),
    onSuccess: async (result) => {
      // Only a replacement that left events in place reports what happened to the old projections.
      const left = result.conflicts > 0 ? removalResultSentences(i18n, result, destinationName) : []
      onReplaced(result.rule.id, [t("ruleDetails.replacement.replaced"), ...left].join(" "))
      await leave()
    },
    // An interrupted replacement leaves the new draft and a retryable old rule behind.
    onError: invalidate,
  })

  return (
    <section className="rule-section page-card" aria-labelledby="replace-title">
      <div className="section-heading">
        <div>
          <h2 id="replace-title">{t("ruleDetails.replacement.title")}</h2>
          <p>{t("ruleDetails.replacement.intro")}</p>
        </div>
        {!open && (
          <Button
            ref={toggle}
            variant="outline"
            onClick={() => {
              replace.reset()
              setOpen(true)
            }}
            aria-expanded={open}
            aria-controls="replace-form"
          >
            {t("ruleDetails.replacement.open")}
          </Button>
        )}
      </div>
      {open && (
        <ReplacementForm
          detail={detail}
          accounts={connected}
          draft={draft}
          sourceCalendars={sourceCalendars.data}
          destinationCalendars={destinationCalendars.data}
          firstField={firstField}
          effective={effective}
          destinationName={destinationName}
          destinationConnected={destinationConnected}
          pending={replace.isPending}
          error={replace.error}
          onEdit={(change) => setEdits((current) => ({ ...current, ...change }))}
          onHandling={setHandling}
          onReplace={() => replace.mutate()}
          onCancel={() => setOpen(false)}
        />
      )}
    </section>
  )
}

/** The replacement draft and its confirmation; an edit always withdraws a pending confirmation. */
function ReplacementForm({
  detail,
  accounts,
  draft,
  sourceCalendars,
  destinationCalendars,
  firstField,
  effective,
  destinationName,
  destinationConnected,
  pending,
  error,
  onEdit,
  onHandling,
  onReplace,
  onCancel,
}: {
  detail: RuleDetail
  accounts: ConnectedAccount[]
  draft: EndpointDraft
  sourceCalendars: DiscoveredCalendar[] | undefined
  destinationCalendars: DiscoveredCalendar[] | undefined
  firstField: RefObject<HTMLSelectElement | null>
  effective: ProjectionHandling
  destinationName: string
  destinationConnected: boolean
  pending: boolean
  error: Error | null
  onEdit: (change: Partial<EndpointDraft>) => void
  onHandling: (value: ProjectionHandling) => void
  onReplace: () => void
  onCancel: () => void
}) {
  const i18n = useI18n()
  const { t } = i18n
  const returnFocus = useRef<HTMLButtonElement>(null)
  const [confirming, setConfirming] = useState(false)
  const { sameEndpoint, canSubmit } = replacementReadiness(detail, draft)

  function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    if (canSubmit) setConfirming(true)
  }

  function edit(change: Partial<EndpointDraft>) {
    onEdit(change)
    setConfirming(false)
  }

  return (
    <form id="replace-form" className="rule-edit-form" onSubmit={submit}>
      <EndpointFields
        legend={t("ruleDetails.replacement.sourceLegend")}
        idPrefix="replace-source"
        firstField={firstField}
        accounts={accounts}
        account={draft.sourceAccount}
        calendar={draft.sourceCalendar}
        calendars={sourceCalendars}
        writableOnly={false}
        onAccount={(value) => edit({ sourceAccount: value, sourceCalendar: "" })}
        onCalendar={(value) => edit({ sourceCalendar: value })}
      />
      <EndpointFields
        legend={t("ruleDetails.replacement.destinationLegend")}
        idPrefix="replace-destination"
        accounts={accounts}
        account={draft.destinationAccount}
        calendar={draft.destinationCalendar}
        calendars={destinationCalendars}
        writableOnly
        errorId={sameEndpoint ? "replace-destination-error" : undefined}
        onAccount={(value) => edit({ destinationAccount: value, destinationCalendar: "" })}
        onCalendar={(value) => edit({ destinationCalendar: value })}
      />
      <ProjectionChoice
        name="replace-projections"
        value={effective}
        onChange={(value) => {
          onHandling(value)
          setConfirming(false)
        }}
        mappingCount={detail.mapping_count}
        destinationName={destinationName}
        deleteAvailable={destinationConnected}
      />
      {sameEndpoint && (
        <p id="replace-destination-error" className="field-error" role="alert">
          {t("ruleDetails.replacement.sameEndpoint")}
        </p>
      )}
      {error && <div className="inline-error" role="alert">{apiErrorMessage(i18n, error)}</div>}
      <div className="form-actions">
        <Button
          ref={returnFocus}
          type="submit"
          variant="outline"
          disabled={!canSubmit || pending}
          aria-expanded={confirming}
          aria-controls="replace-confirmation"
        >
          {t("ruleDetails.replacement.review")}
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={() => {
            setConfirming(false)
            onCancel()
          }}
          disabled={pending}
        >
          {t("ruleDetails.replacement.cancel")}
        </Button>
      </div>
      {confirming && (
        <DestructiveConfirmation
          id="replace-confirmation"
          title={t("ruleDetails.replacement.confirmTitle")}
          body={t("ruleDetails.replacement.confirmBody", {
            consequence: removalConsequence(i18n, effective, detail.mapping_count, destinationName),
          })}
          cancelLabel={t("ruleDetails.replacement.keep")}
          confirmLabel={replacementConfirmLabel(i18n, effective, detail.mapping_count)}
          pendingLabel={t("ruleDetails.replacement.pending")}
          pending={pending}
          onConfirm={onReplace}
          onCancel={() => {
            setConfirming(false)
            returnFocus.current?.focus()
          }}
        />
      )}
    </form>
  )
}

/** Exported so rendered tests can exercise calendar-option filtering without the full replacement form. */
export function EndpointFields({
  legend,
  idPrefix,
  firstField,
  errorId,
  accounts,
  account,
  calendar,
  calendars,
  writableOnly,
  onAccount,
  onCalendar,
}: {
  legend: string
  idPrefix: string
  firstField?: RefObject<HTMLSelectElement | null>
  errorId?: string | undefined
  accounts: ConnectedAccount[]
  account: string
  calendar: string
  calendars: DiscoveredCalendar[] | undefined
  writableOnly: boolean
  onAccount: (value: string) => void
  onCalendar: (value: string) => void
}) {
  const { t } = useI18n()
  const options = writableOnly ? writableCalendars(calendars) : (calendars ?? [])
  return (
    <fieldset className="endpoint-fields">
      <legend>{legend}</legend>
      <div className="field-stack">
        <Label htmlFor={`${idPrefix}-account`}>{t("ruleDetails.endpointFields.account")}</Label>
        <NativeSelect ref={firstField} id={`${idPrefix}-account`} value={account} onChange={(event) => onAccount(event.target.value)}>
          {accounts.map((item) => (
            <option key={item.id} value={item.id}>
              {t("ruleDetails.endpointFields.accountOption", { name: item.display_name, email: item.email })}
            </option>
          ))}
        </NativeSelect>
      </div>
      <div className="field-stack">
        <Label htmlFor={`${idPrefix}-calendar`}>
          {writableOnly ? t("ruleDetails.endpointFields.writableCalendar") : t("ruleDetails.endpointFields.calendar")}
        </Label>
        <NativeSelect
          id={`${idPrefix}-calendar`}
          value={calendar}
          onChange={(event) => onCalendar(event.target.value)}
          aria-invalid={errorId ? true : undefined}
          aria-describedby={errorId}
        >
          <option value="" disabled>
            {t("ruleDetails.endpointFields.chooseCalendar")}
          </option>
          {options.map((item) => (
            <option key={item.id} value={item.id}>
              {item.summary}
            </option>
          ))}
        </NativeSelect>
      </div>
    </fieldset>
  )
}
