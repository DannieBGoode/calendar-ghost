import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowRight } from "lucide-react"
import { useEffect, useRef, useState, type SyntheticEvent } from "react"

import { AccountSelect } from "@/components/account-select"
import { LiveAnnouncement } from "@/components/rule-commands"
import { RulePolicyFields } from "@/components/rule-policy-fields"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { NativeSelect } from "@/components/ui/native-select"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import type { I18n } from "@/i18n/translator"
import type { MessageKey } from "@/i18n/types"
import { api, type ConnectedAccount, type DiscoveredCalendar, type Rule, type RulePolicyPayload } from "@/lib/api"
import { CREATE_RULE_KEY } from "@/lib/rule-draft"
import { firstOtherCalendar, writableCalendars } from "@/lib/writable-calendars"

const CALENDAR_STALE_TIME = 5 * 60 * 1000

// New rules default to Busy-Only Projection and leave out birthdays (CONTEXT.md).
const DEFAULT_POLICY: RulePolicyPayload = {
  privacy_policy: "busy_only",
  sync_all_day_events: true,
  sync_birthdays: false,
  tentative_events: "mark",
  unanswered_invitations: "as_tentative",
}
type CalendarQuery = {
  data: DiscoveredCalendar[] | undefined
  isPending: boolean
  isFetching: boolean
  error: Error | null
}

/** Exported so rendered tests can exercise calendar-picker wiring without the full rules list. */
export function RuleBuilder({
  accounts,
  onCreated,
  onCancel,
}: {
  accounts: ConnectedAccount[]
  onCreated: (rule: Rule) => void
  onCancel: () => void
}) {
  const i18n = useI18n()
  const { t } = i18n
  const queryClient = useQueryClient()
  const heading = useRef<HTMLHeadingElement>(null)
  const draft = useDraftEndpoints(accounts)
  const [policy, setPolicy] = useState(DEFAULT_POLICY)

  useEffect(() => {
    heading.current?.focus()
  }, [])

  const create = useMutation({
    mutationKey: CREATE_RULE_KEY,
    mutationFn: () =>
      api.createRule({
        source: { connected_account_id: draft.resolvedSourceAccount, calendar_id: draft.resolvedSourceCalendar },
        destination: { connected_account_id: draft.resolvedDestinationAccount, calendar_id: draft.resolvedDestinationCalendar },
        ...policy,
      }),
    onSuccess: async (rule) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["rules"] }),
        queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
      ])
      onCreated(rule)
    },
  })

  function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    if (draft.complete && !create.isPending) create.mutate()
  }

  return (
    <section className="rule-builder page-card" id="rule-builder" aria-labelledby="builder-title">
      <div className="section-heading">
        <div>
          <h2 id="builder-title" ref={heading} tabIndex={-1}>{t("rules.builder.heading")}</h2>
          <p>{t("rules.builder.intro")}</p>
        </div>
      </div>
      <form className="rule-form" onSubmit={submit}>
        <SourceFieldset
          accounts={accounts}
          account={draft.resolvedSourceAccount}
          calendar={draft.resolvedSourceCalendar}
          calendars={draft.sourceCalendars}
          onAccountChange={draft.chooseSourceAccount}
          onCalendarChange={draft.setSourceCalendar}
        />
        <div className="direction-marker" aria-hidden="true"><ArrowRight /></div>
        <DestinationFieldset
          accounts={accounts}
          account={draft.resolvedDestinationAccount}
          calendar={draft.resolvedDestinationCalendar}
          calendars={draft.destinationCalendars}
          sameEndpoint={draft.sameEndpoint}
          onAccountChange={draft.chooseDestinationAccount}
          onCalendarChange={draft.setDestinationCalendar}
        />
        <fieldset className="policy-fields">
          <legend>{t("rules.builder.policyLegend")}</legend>
          <RulePolicyFields
            idPrefix=""
            policy={policy}
            destination={draft.destinationName ?? t("rules.policy.destinationFallback")}
            onChange={setPolicy}
          />
        </fieldset>
        {create.error && <div className="inline-error" role="alert">{apiErrorMessage(i18n, create.error)}</div>}
        <BuilderActions ready={draft.complete} saving={create.isPending} onCancel={onCancel} />
      </form>
    </section>
  )
}

function BuilderActions({ ready, saving, onCancel }: { ready: boolean; saving: boolean; onCancel: () => void }) {
  const { t } = useI18n()
  return (
    <>
      <div className="form-actions">
        {/* A save in flight cannot be called back, so the builder stays open until it ends. */}
        <Button type="button" variant="outline" onClick={onCancel} disabled={saving}>
          {t("rules.builder.cancel")}
        </Button>
        {/* aria-disabled keeps focus on the button while it saves; the form ignores the click. */}
        <Button type="submit" aria-disabled={!ready || saving || undefined} aria-busy={saving}>
          {saving ? t("rules.builder.saving") : t("rules.builder.submit")}
        </Button>
      </div>
      <LiveAnnouncement text={saving ? t("rules.builder.saving") : ""} />
    </>
  )
}

/** The chosen accounts. Until the administrator picks, they default to the first two accounts. */
function useDraftAccounts(accounts: ConnectedAccount[]) {
  const [sourceAccount, setSourceAccount] = useState("")
  const [destinationAccount, setDestinationAccount] = useState("")

  const resolvedSourceAccount = sourceAccount || accounts[0]?.id || ""
  const resolvedDestinationAccount = destinationAccount || accounts[1]?.id || accounts[0]?.id || ""

  return { resolvedSourceAccount, resolvedDestinationAccount, setSourceAccount, setDestinationAccount }
}

/** The draft's Source and Destination Calendars, and the calendars each chosen account offers. */
function useDraftEndpoints(accounts: ConnectedAccount[]) {
  const { resolvedSourceAccount, resolvedDestinationAccount, setSourceAccount, setDestinationAccount } =
    useDraftAccounts(accounts)
  const [sourceCalendar, setSourceCalendar] = useState("")
  const [destinationCalendar, setDestinationCalendar] = useState("")

  const sourceCalendars = useQuery({
    queryKey: ["calendars", resolvedSourceAccount],
    queryFn: () => api.calendars(resolvedSourceAccount),
    enabled: Boolean(resolvedSourceAccount),
    staleTime: CALENDAR_STALE_TIME,
  })
  const destinationCalendars = useQuery({
    queryKey: ["calendars", resolvedDestinationAccount],
    queryFn: () => api.calendars(resolvedDestinationAccount),
    enabled: Boolean(resolvedDestinationAccount),
    staleTime: CALENDAR_STALE_TIME,
  })

  const resolvedSourceCalendar = sourceCalendar || sourceCalendars.data?.[0]?.id || ""
  // Default to a destination other than the source so the builder never opens in an error.
  const resolvedDestinationCalendar =
    destinationCalendar ||
    firstOtherCalendar(
      destinationCalendars.data,
      resolvedSourceAccount === resolvedDestinationAccount ? resolvedSourceCalendar : null,
    )

  const sameEndpoint =
    resolvedSourceAccount === resolvedDestinationAccount && resolvedSourceCalendar === resolvedDestinationCalendar

  return {
    resolvedSourceAccount,
    resolvedDestinationAccount,
    resolvedSourceCalendar,
    resolvedDestinationCalendar,
    sameEndpoint,
    complete:
      !sameEndpoint &&
      [resolvedSourceAccount, resolvedDestinationAccount, resolvedSourceCalendar, resolvedDestinationCalendar].every(Boolean),
    destinationName: calendarName(destinationCalendars.data, resolvedDestinationCalendar),
    sourceCalendars,
    destinationCalendars,
    setSourceCalendar,
    setDestinationCalendar,
    chooseSourceAccount: (value: string) => {
      setSourceAccount(value)
      setSourceCalendar("")
    },
    chooseDestinationAccount: (value: string) => {
      setDestinationAccount(value)
      setDestinationCalendar("")
    },
  }
}

function calendarName(calendars: DiscoveredCalendar[] | undefined, id: string): string | undefined {
  return calendars?.find((calendar) => calendar.id === id)?.summary
}

type FieldsetProps = {
  accounts: ConnectedAccount[]
  account: string
  calendar: string
  calendars: CalendarQuery
  onAccountChange: (value: string) => void
  onCalendarChange: (value: string) => void
}

function SourceFieldset({ accounts, account, calendar, calendars, onAccountChange, onCalendarChange }: FieldsetProps) {
  const i18n = useI18n()
  const { t } = i18n
  const status = calendarStatus(i18n, calendars, calendars.data?.length ?? 0, "rules.builder.noCalendars")
  return (
    <fieldset>
      <legend>{t("rules.builder.sourceLegend")}</legend>
      <div className="field-stack">
        <Label id="source-account-label" htmlFor="source-account">{t("rules.builder.account")}</Label>
        <AccountSelect
          id="source-account"
          labelId="source-account-label"
          accounts={accounts}
          value={account}
          onChange={onAccountChange}
        />
      </div>
      <div className="field-stack">
        <Label htmlFor="source-calendar">{t("rules.builder.calendarLabel")}</Label>
        <NativeSelect
          id="source-calendar"
          value={calendar}
          onChange={(event) => onCalendarChange(event.target.value)}
          aria-disabled={!calendars.data?.length || undefined}
          aria-describedby={status ? "source-calendar-status" : undefined}
        >
          {calendars.data?.map((option) => <option key={option.id} value={option.id}>{option.summary}</option>)}
        </NativeSelect>
        <p id="source-calendar-status" className="field-hint" role="status">{status}</p>
      </div>
    </fieldset>
  )
}

function DestinationFieldset({
  accounts,
  account,
  calendar,
  calendars,
  sameEndpoint,
  onAccountChange,
  onCalendarChange,
}: FieldsetProps & { sameEndpoint: boolean }) {
  const i18n = useI18n()
  const { t } = i18n
  const writable = writableCalendars(calendars.data)
  const status = calendarStatus(i18n, calendars, writable.length, "rules.builder.noWritableCalendars")
  return (
    <fieldset>
      <legend>{t("rules.builder.destinationLegend")}</legend>
      <div className="field-stack">
        <Label id="destination-account-label" htmlFor="destination-account">{t("rules.builder.account")}</Label>
        <AccountSelect
          id="destination-account"
          labelId="destination-account-label"
          accounts={accounts}
          value={account}
          onChange={onAccountChange}
        />
      </div>
      <div className="field-stack">
        <Label htmlFor="destination-calendar">{t("rules.builder.destinationCalendarLabel")}</Label>
        <NativeSelect
          id="destination-calendar"
          value={calendar}
          onChange={(event) => onCalendarChange(event.target.value)}
          aria-disabled={!writable.length || undefined}
          aria-invalid={sameEndpoint || undefined}
          aria-describedby={
            sameEndpoint ? "destination-calendar-error" : status ? "destination-calendar-status" : undefined
          }
        >
          {writable.map((option) => <option key={option.id} value={option.id}>{option.summary}</option>)}
        </NativeSelect>
        <p id="destination-calendar-status" className="field-hint" role="status">{sameEndpoint ? null : status}</p>
        {sameEndpoint && (
          <p id="destination-calendar-error" className="field-error" role="alert">
            {t("rules.builder.sameEndpointError")}
          </p>
        )}
      </div>
    </fieldset>
  )
}

function calendarStatus(
  i18n: I18n,
  query: { isPending: boolean; isFetching: boolean; error: Error | null },
  available: number,
  empty: MessageKey,
): string | null {
  if (query.error) return i18n.t("rules.builder.calendarsLoadError", { reason: apiErrorMessage(i18n, query.error) })
  if (query.isPending && query.isFetching) return i18n.t("rules.builder.loadingCalendars")
  if (!query.isPending && available === 0) return i18n.t(empty)
  return null
}
