import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowRight } from "lucide-react"
import { useEffect, useRef, useState, type SyntheticEvent } from "react"

import { AccountSelect } from "@/components/account-select"
import { InvitationResponseFields } from "@/components/invitation-response-fields"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { NativeSelect } from "@/components/ui/native-select"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import type { I18n } from "@/i18n/translator"
import type { MessageKey } from "@/i18n/types"
import {
  api,
  type ConnectedAccount,
  type DiscoveredCalendar,
  type Rule,
  type TentativeEvents,
  type UnansweredInvitations,
} from "@/lib/api"
import { OWN_OVERVIEW_QUERY } from "@/lib/operator-overview"
import { firstOtherCalendar, writableCalendars } from "@/lib/writable-calendars"

const CALENDAR_STALE_TIME = 5 * 60 * 1000

type Privacy = "busy_only" | "copy_details"
type Responses = {
  tentative_events: TentativeEvents
  unanswered_invitations: UnansweredInvitations
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
}: {
  accounts: ConnectedAccount[]
  onCreated: (rule: Rule) => void
}) {
  const i18n = useI18n()
  const { t } = i18n
  const queryClient = useQueryClient()
  const heading = useRef<HTMLHeadingElement>(null)
  const draft = useDraftEndpoints(accounts)
  const [privacy, setPrivacy] = useState<Privacy>("busy_only")
  const [allDay, setAllDay] = useState(true)
  const [responses, setResponses] = useState<Responses>({ tentative_events: "mark", unanswered_invitations: "as_tentative" })

  useEffect(() => {
    heading.current?.focus()
  }, [])

  const create = useMutation({
    mutationFn: () =>
      api.createRule({
        source: { connected_account_id: draft.resolvedSourceAccount, calendar_id: draft.resolvedSourceCalendar },
        destination: { connected_account_id: draft.resolvedDestinationAccount, calendar_id: draft.resolvedDestinationCalendar },
        privacy_policy: privacy,
        sync_all_day_events: allDay,
        ...responses,
      }),
    onSuccess: async (rule) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["rules"] }),
        queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
        queryClient.invalidateQueries({ queryKey: OWN_OVERVIEW_QUERY }),
      ])
      onCreated(rule)
    },
  })

  const sameEndpoint =
    draft.resolvedSourceAccount === draft.resolvedDestinationAccount &&
    draft.resolvedSourceCalendar === draft.resolvedDestinationCalendar
  const canSubmit = Boolean(
    draft.resolvedSourceAccount &&
      draft.resolvedDestinationAccount &&
      draft.resolvedSourceCalendar &&
      draft.resolvedDestinationCalendar &&
      !sameEndpoint,
  )

  function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    if (canSubmit) create.mutate()
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
          sameEndpoint={sameEndpoint}
          onAccountChange={draft.chooseDestinationAccount}
          onCalendarChange={draft.setDestinationCalendar}
        />
        <fieldset className="policy-fields">
          <legend>{t("rules.builder.policyLegend")}</legend>
          <div className="field-stack">
            <Label htmlFor="privacy-policy">{t("rules.builder.privacyLabel")}</Label>
            <NativeSelect id="privacy-policy" value={privacy} onChange={(event) => setPrivacy(event.target.value as Privacy)}>
              <option value="busy_only">{t("rules.builder.privacyOption.busyOnly")}</option>
              <option value="copy_details">{t("rules.builder.privacyOption.copyDetails")}</option>
            </NativeSelect>
          </div>
          <label className="checkbox-row">
            <input type="checkbox" checked={allDay} onChange={(event) => setAllDay(event.target.checked)} />
            <span>
              <strong>{t("rules.builder.allDay.label")}</strong>
              <small>{t("rules.builder.allDay.hint")}</small>
            </span>
          </label>
          <InvitationResponseFields
            idPrefix=""
            policy={{ privacy_policy: privacy, ...responses }}
            onChange={setResponses}
          />
        </fieldset>
        {create.error && <div className="inline-error" role="alert">{apiErrorMessage(i18n, create.error)}</div>}
        <div className="form-actions">
          <Button type="submit" disabled={!canSubmit || create.isPending}>
            {create.isPending ? t("rules.builder.saving") : t("rules.builder.submit")}
          </Button>
        </div>
      </form>
    </section>
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

  return {
    resolvedSourceAccount,
    resolvedDestinationAccount,
    resolvedSourceCalendar,
    resolvedDestinationCalendar,
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
        <Label id="source-account-label" htmlFor="source-account">{t("rules.builder.googleAccount")}</Label>
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
          disabled={!calendars.data?.length}
          aria-describedby={status ? "source-calendar-status" : undefined}
        >
          {calendars.data?.map((option) => <option key={option.id} value={option.id}>{option.summary}</option>)}
        </NativeSelect>
        {status && <p id="source-calendar-status" className="field-hint">{status}</p>}
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
        <Label id="destination-account-label" htmlFor="destination-account">{t("rules.builder.googleAccount")}</Label>
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
          disabled={!writable.length}
          aria-invalid={sameEndpoint || undefined}
          aria-describedby={
            sameEndpoint ? "destination-calendar-error" : status ? "destination-calendar-status" : undefined
          }
        >
          {writable.map((option) => <option key={option.id} value={option.id}>{option.summary}</option>)}
        </NativeSelect>
        {sameEndpoint ? (
          <p id="destination-calendar-error" className="field-error" role="alert">
            {t("rules.builder.sameEndpointError")}
          </p>
        ) : (
          status && <p id="destination-calendar-status" className="field-hint">{status}</p>
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
