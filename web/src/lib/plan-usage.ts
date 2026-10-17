import type { I18n } from "@/i18n/translator"
import type { MessageKey } from "@/i18n/types"
import type { LimitUse, PersonPlanOverview, SyncInterval } from "@/lib/api"

/**
 * The words of a person's Plan card: who gave the Plan and whether it limits them now, then one
 * row per limit with how much of it they use. Counts come from the Operator Overview's `use`;
 * nothing here counts on its own. Rows hold nouns and numbers; sentences are the card's summary
 * and the note under a limit they are over.
 */

/** Which limit a usage row shows. */
type UsageLimit = "rules" | "accounts" | "tokens" | "speed"

/** A meter's numbers and words: never past the limit in width, always the real count in words. */
type UsageMeter = { value: number; max: number; valueText: string; tone: "neutral" | "over" }

/** A chip beside a count: "Limit reached" and "Would be over" neutral, "Over" in Attention Ochre. */
type UsageChip = { text: string; tone: "neutral" | "attention" }

export type UsageRow = {
  limit: UsageLimit
  title: string
  /** What counts toward the limit, in one line. */
  hint: string
  /** What the row says where it has no meter: "No limit", "Free includes none." */
  detail: string | null
  meter: UsageMeter | null
  /** The count against the limit, "1 of 1", or how soon calendars sync. */
  value: string
  /** The value is a quiet word, as "Not included", rather than a count. */
  quiet: boolean
  chip: UsageChip | null
  /** How soon the Plan syncs, on the Sync speed row, for its icon. */
  speed: SyncInterval | null
  /** Past an enforced limit: what keeps working and how to make room. */
  note: string | null
}

type CountLimit = Exclude<UsageLimit, "speed">

const TITLES: Record<CountLimit, { title: MessageKey; hint: MessageKey; note: MessageKey }> = {
  rules: { title: "people.usage.rules", hint: "people.usage.rulesHint", note: "people.usage.note.rules" },
  accounts: { title: "people.usage.accounts", hint: "people.usage.accountsHint", note: "people.usage.note.accounts" },
  tokens: { title: "people.usage.tokens", hint: "people.usage.tokensHint", note: "people.usage.note.tokens" },
}

/** Whose row it is and what their Plan is called, for the sentences, and whether Plans are on. */
type RowContext = { person: string; name: string; enforced: boolean }

function emptyRow(i18n: I18n, limit: CountLimit): Omit<UsageRow, "meter" | "value" | "chip" | "note" | "detail"> {
  const words = TITLES[limit]
  return { limit, title: i18n.t(words.title), hint: i18n.t(words.hint), quiet: false, speed: null }
}

/** Past a limit: "Over" while Plans are on, "Would be over" while off, with what keeps working only when on. */
function pastLimit(i18n: I18n, limit: CountLimit, { in_use, allowed }: LimitUse, context: RowContext) {
  const { t } = i18n
  const none = limit === "tokens" && allowed === 0
  const params = { person: context.person, name: context.name, count: in_use, allowed: allowed ?? 0 }
  return {
    chip: context.enforced ? { text: t("people.usage.over"), tone: "attention" as const } : { text: t("people.usage.wouldBeOver"), tone: "neutral" as const },
    note: context.enforced ? t(none ? "people.usage.note.tokensNone" : TITLES[limit].note, params) : null,
  }
}

/** What a meter says in words: "1 of 1, limit reached", "2 of 1, over the limit", or "0 of 1". */
function meterWords({ t }: I18n, { in_use, allowed }: LimitUse & { allowed: number }, enforced: boolean): string {
  const numbers = { used: in_use, limit: allowed }
  if (in_use > allowed) return t(enforced ? "people.usage.valueOver" : "people.usage.valueWouldBeOver", numbers)
  return t(in_use === allowed ? "people.usage.valueReached" : "people.usage.of", numbers)
}

/** A limit's meter, its "1 of 1", and its chip: at the limit, past it, or within it. */
function meteredRow(i18n: I18n, limit: CountLimit, use: LimitUse & { allowed: number }, context: RowContext): UsageRow {
  const { t } = i18n
  const numbers = { used: use.in_use, limit: use.allowed }
  const over = use.in_use > use.allowed
  const reached = use.in_use === use.allowed
  const valueText = meterWords(i18n, use, context.enforced)
  const past = over ? pastLimit(i18n, limit, use, context) : null
  return {
    ...emptyRow(i18n, limit),
    detail: null,
    meter: { value: use.in_use, max: use.allowed, valueText, tone: over && context.enforced ? "over" : "neutral" },
    value: t("people.usage.of", numbers),
    chip: past?.chip ?? (reached ? { text: t("people.usage.limitReached"), tone: "neutral" } : null),
    note: past?.note ?? null,
  }
}

/** One count against its limit: no limit in words, none included in words, or a meter. */
function countRow(i18n: I18n, limit: CountLimit, use: LimitUse, context: RowContext): UsageRow {
  const { t } = i18n
  const { allowed, in_use } = use
  if (allowed === null) {
    return { ...emptyRow(i18n, limit), detail: t("people.usage.noLimit"), meter: null, value: t("people.usage.inUse", { used: in_use }), chip: null, note: null }
  }
  if (allowed === 0) {
    const past = in_use > 0 ? pastLimit(i18n, limit, use, context) : null
    return {
      ...emptyRow(i18n, limit),
      detail: t("people.usage.includesNone", { name: context.name }),
      meter: null,
      value: past ? t("people.usage.inUse", { used: in_use }) : t("people.usage.notIncluded"),
      quiet: past === null,
      chip: past?.chip ?? null,
      note: past?.note ?? null,
    }
  }
  return meteredRow(i18n, limit, { in_use, allowed }, context)
}

/** How soon their calendars sync, and when Instant sync is not part of the Plan. */
function speedRow(i18n: I18n, speed: SyncInterval, name: string): UsageRow {
  const { t } = i18n
  return {
    limit: "speed",
    title: t("people.usage.speed"),
    hint: t("people.usage.speedHint"),
    detail: speed === "instant" ? null : t("people.usage.noInstant", { name }),
    meter: null,
    value: t(`people.usage.interval.${speed}`),
    quiet: false,
    chip: null,
    speed,
    note: null,
  }
}

/**
 * One row per limit of the Plan someone has, with how much of it they use: Active rules, Calendar
 * accounts, Integration Tokens, then Sync speed. None without a Plan or its use. `person` names
 * them in the sentence under a limit they are over.
 */
export function planUsageRows(i18n: I18n, plan: PersonPlanOverview, person: string): UsageRow[] {
  const { use, has } = plan
  if (!use || !has) return []
  const context: RowContext = { person, name: has.name, enforced: plan.basis === "plan" }
  return [
    countRow(i18n, "rules", use.rules, context),
    countRow(i18n, "accounts", use.connected_accounts, context),
    countRow(i18n, "tokens", use.integration_tokens, context),
    speedRow(i18n, use.sync_interval, has.name),
  ]
}

/** When the Plan was given, as "Oct 12", with the year when it was another year. */
function givenDay(i18n: I18n, at: string, now: number): string {
  const sameYear = new Date(at).getFullYear() === new Date(now).getFullYear()
  return i18n.format.date(at, { month: "short", day: "numeric", ...(sameYear ? {} : { year: "numeric" }) })
}

/** How they came to have the Plan: the default, given by someone on a day, or their own. */
function origin(i18n: I18n, plan: PersonPlanOverview, now: number): string {
  const { t } = i18n
  if (plan.has?.on_default) return t("people.person.plan.default")
  const { assigned_by: by, assigned_at: at } = plan
  if (at !== null) {
    const date = givenDay(i18n, at, now)
    return by === null ? t("people.person.plan.givenOn", { date }) : t("people.person.plan.givenBy", { email: by, date })
  }
  return t("people.person.plan.own")
}

/** Whose card it is: their name, whether they administer, and now, for the day the Plan was given. */
type CardReader = { name: string; administrator: boolean; now: number }

/**
 * The Plan card's sentence: who gave the Plan and when, then whether it limits them now, as "Given
 * by dana@example.test on Oct 12. Plans are on, so it limits robin@example.test now." An
 * administrator's card says only that no plan limits administrators.
 */
export function planCardSummary(i18n: I18n, plan: PersonPlanOverview, { name, administrator, now }: CardReader): string {
  const { t } = i18n
  if (administrator || plan.basis === "administrator") return t("people.person.plan.administrator")
  if (!plan.has) return t("people.person.plan.none")
  const effect = plan.basis === "plan" ? t("people.person.plan.on", { person: name }) : t("people.person.plan.off")
  return t("people.person.plan.summary", { origin: origin(i18n, plan, now), effect })
}
