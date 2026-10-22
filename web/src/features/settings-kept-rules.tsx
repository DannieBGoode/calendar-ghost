import { Check } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import { ApiError, type OwnPlan, type RuleSummary } from "@/lib/api"
import { useKeptRules } from "@/lib/use-kept-rules"

/** One progressively disclosed step, keeping the editor in the Plan card. */
export function KeptRulesForm({ plan }: { plan: OwnPlan }) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const trigger = useRef<HTMLButtonElement>(null)
  function close() {
    setOpen(false)
    window.setTimeout(() => trigger.current?.focus(), 0)
  }
  return (
    <div className="border-t border-border pt-4">
      <Button ref={trigger} type="button" variant="outline" aria-expanded={open} aria-controls="kept-rules-form" onClick={() => setOpen(true)} hidden={open} className={open ? "hidden" : undefined}>
        {t("settings.ownPlan.keep.open")}
      </Button>
      {open && <KeepEditor plan={plan} onCancel={close} />}
    </div>
  )
}

function useKeepEditor(initial: OwnPlan) {
  const i18n = useI18n()
  const { t } = i18n
  const commands = useKeptRules()
  const plan = commands.plan.data ?? initial
  const [selected, setSelected] = useState(() => initial.rules.filter((rule) => rule.kept).map((rule) => rule.rule_id))
  const [feedback, setFeedback] = useState({ saved: false, error: "", review: false })
  const pending = commands.pending
  const limit = plan.limits?.rules
  const rows = namedRules(plan, commands.names.data)
  const complete = rows.length === plan.rules.length
  const namesFailed = commands.names.isError || !complete
  const maximum = typeof limit === "number" ? limit : Infinity
  const atMaximum = selected.length >= maximum
  const overMaximum = selected.length > maximum
  const selectedSet = new Set(selected)
  const reviewAvailable = complete && !commands.plan.isError
  const blocked = pending || feedback.review || namesFailed || overMaximum || commands.plan.isError
  function toggle(id: string, checked: boolean) {
    if (pending || (checked && atMaximum)) return
    setSelected((current) => checked ? [...current, id] : current.filter((item) => item !== id))
  }
  async function save() {
    if (blocked) return
    setFeedback({ saved: false, error: "", review: false })
    try {
      // The whole set is deliberate, including an empty or unchanged selection.
      await commands.save.mutateAsync([...selected].sort())
    } catch (error) {
      const stale = error instanceof ApiError && error.status === 404
      setFeedback({ saved: false, error: stale ? t("settings.ownPlan.keep.stale") : apiErrorMessage(i18n, error), review: stale })
      if (stale || (error instanceof ApiError && error.code === "too_many_kept_rules")) await commands.refresh()
      return
    }
    setFeedback({ saved: true, error: "", review: false })
  }
  function review() {
    const eligible = new Set(plan.rules.map((rule) => rule.rule_id))
    setSelected((current) => current.filter((id) => eligible.has(id)))
    setFeedback((current) => ({ ...current, review: false, error: "" }))
  }
  return { i18n, commands, selected, selectedSet, feedback, pending, limit, rows, complete, blocked, atMaximum, namesFailed, reviewAvailable, save, toggle, review }
}

function KeepEditor({ plan, onCancel }: { plan: OwnPlan; onCancel: () => void }) {
  const editor = useKeepEditor(plan)
  const { i18n, commands, selected, selectedSet, feedback, pending, limit, rows, complete, blocked, atMaximum, namesFailed, reviewAvailable, save, toggle, review } = editor
  const { t } = i18n
  const heading = useRef<HTMLLegendElement>(null)
  useEffect(() => { heading.current?.focus() }, [])
  return (
    <form id="kept-rules-form" className="grid gap-4" aria-busy={pending} onSubmit={(event) => { event.preventDefault(); void save() }}>
      <fieldset className="grid min-w-0 grid-cols-1 gap-3" aria-describedby="kept-rules-capacity kept-rules-hint">
        <legend ref={heading} tabIndex={-1} className="font-semibold">{t("settings.ownPlan.keep.open")}</legend>
        <p id="kept-rules-hint" className="text-sm text-muted-foreground">{t("settings.ownPlan.keep.hint")}</p>
        <p id="kept-rules-capacity" className="text-sm">{t("settings.ownPlan.keep.capacity", { count: selected.length, maximum: typeof limit === "number" ? i18n.format.number(limit) : t("settings.ownPlan.keep.unlimited") })}</p>
        {namesFailed && <NamesFailure loading={commands.names.isPending} retry={() => void commands.names.refetch()} />}
        {complete && rows.map(({ standing, rule }) => <KeepRow key={standing.rule_id} standing={standing} rule={rule} checked={selectedSet.has(standing.rule_id)} pending={pending} atMaximum={atMaximum} onChange={(checked) => toggle(standing.rule_id, checked)} />)}
      </fieldset>
      {feedback.error && <p className="inline-error" role="alert">{feedback.error}</p>}
      {feedback.review && <ReviewChoices pending={pending} complete={reviewAvailable} onReview={review} />}
      <p role="status" aria-live="polite" className="text-sm">{feedback.saved ? t("settings.ownPlan.keep.saved") : ""}</p>
      {commands.refreshFailed && <div className="inline-error" role="alert"><span>{t("settings.ownPlan.keep.refreshFailed")}</span><Button type="button" variant="outline" aria-disabled={pending} onClick={() => { if (!pending) void commands.refresh() }}>{t("settings.ownPlan.keep.refresh")}</Button></div>}
      <div className="flex flex-wrap gap-2">
        {complete && <Button type="submit" aria-disabled={blocked}>{t(pending ? "settings.ownPlan.keep.saving" : "settings.ownPlan.keep.save")}</Button>}
        <Button type="button" variant="outline" aria-disabled={pending} onClick={() => { if (!pending) onCancel() }}>{t("settings.ownAccount.cancel")}</Button>
      </div>
    </form>
  )
}

function NamesFailure({ loading, retry }: { loading: boolean; retry: () => void }) {
  const { t } = useI18n()
  if (loading) return <p role="status">{t("settings.ownPlan.keep.loading")}</p>
  return <div className="inline-error" role="alert"><span>{t("settings.ownPlan.keep.loadError")}</span><Button type="button" variant="outline" onClick={retry}>{t("common.loadFailure.retry")}</Button></div>
}

type RowProps = { standing: OwnPlan["rules"][number]; rule: RuleSummary; checked: boolean; pending: boolean; atMaximum: boolean; onChange: (checked: boolean) => void }
function KeepRow({ standing, rule, checked, pending, atMaximum, onChange }: RowProps) {
  const { t } = useI18n()
  const status = { counted: t("settings.ownPlan.keep.active"), reserved: t("settings.ownPlan.keep.reserved"), held: t("settings.ownPlan.keep.held") }
  const id = `keep-rule-${standing.rule_id}`
  return (
    <label className="flex min-w-0 items-start gap-3 rounded-md border border-border p-3">
      <Checkbox id={id} checked={checked} pending={pending || (!checked && atMaximum)} onCheckedChange={onChange} aria-describedby="kept-rules-capacity" />
      <span className="min-w-0 flex-1 text-sm">
        <span className="block break-words font-medium">{t("settings.ownPlan.keep.direction", { source: rule.source.calendar_name ?? rule.source.calendar_id, destination: rule.destination.calendar_name ?? rule.destination.calendar_id })}</span>
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-muted-foreground">
          <span>{status[standing.place]}</span>
          {standing.kept && <span className="inline-flex min-w-0 items-center gap-1 break-words text-xs"><Check aria-hidden="true" className="size-3.5 shrink-0" /><span>{t("settings.ownPlan.keep.kept")}</span></span>}
        </span>
      </span>
    </label>
  )
}

function ReviewChoices({ pending, complete, onReview }: { pending: boolean; complete: boolean; onReview: () => void }) {
  const { t } = useI18n()
  const blocked = pending || !complete
  return <Button type="button" variant="outline" aria-disabled={blocked} onClick={() => { if (!blocked) onReview() }}>{t("settings.ownPlan.keep.review")}</Button>
}

/** Labels come only from signed-in summaries; standings alone decide eligibility and placement. */
function namedRules(plan: OwnPlan, summaries: RuleSummary[] | undefined) {
  const names = new Map(summaries?.map((rule) => [rule.id, rule]))
  return plan.rules.flatMap((standing) => {
    const rule = names.get(standing.rule_id)
    return rule ? [{ standing, rule }] : []
  })
}
