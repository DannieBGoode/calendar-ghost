import { useMutation } from "@tanstack/react-query"
import { useRef, useState, type SyntheticEvent } from "react"

import { RulePolicyFields } from "@/components/rule-policy-fields"
import { Button } from "@/components/ui/button"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import { api, type RuleDetail, type RulePolicyPayload } from "@/lib/api"
import { policyChanged, policyChangeConsequences } from "@/lib/rule-change"
import { useDisclosureFocus } from "@/lib/use-disclosure-focus"
import { usePlanWarning } from "@/lib/use-own-plan"
import type { RuleFeedback } from "@/lib/use-rule-commands"
import { useRuleInvalidation } from "@/lib/use-rule-refresh"

export function PolicyEditor({
  detail,
  destinationName,
  onSaved,
}: {
  detail: RuleDetail
  destinationName: string
  onSaved: (feedback: RuleFeedback) => void
}) {
  const i18n = useI18n()
  const { t } = i18n
  const invalidate = useRuleInvalidation(detail.id)
  const toggle = useRef<HTMLButtonElement>(null)
  const firstField = useRef<HTMLSelectElement>(null)
  const current: RulePolicyPayload = {
    privacy_policy: detail.privacy_policy,
    sync_all_day_events: detail.sync_all_day_events,
    tentative_events: detail.tentative_events,
    unanswered_invitations: detail.unanswered_invitations,
    sync_birthdays: detail.sync_birthdays,
  }
  const [open, setOpen] = useState(false)
  const [next, setNext] = useState<RulePolicyPayload>(current)
  const changed = policyChanged(current, next)
  // Showing details to everyone who can see the destination is the one change that widens access.
  const widens = current.privacy_policy === "busy_only" && next.privacy_policy === "copy_details"
  const update = useMutation({
    mutationFn: () => api.updateRulePolicy(detail.id, next),
    onSuccess: async () => {
      await invalidate()
      setOpen(false)
      onSaved({ tone: "success", text: t("ruleDetails.policy.saved") })
    },
  })

  useDisclosureFocus(open, firstField, toggle)

  function cancel() {
    setOpen(false)
  }

  function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    if (changed) update.mutate()
  }

  return (
    <section className="rule-section page-card" aria-labelledby="policy-title">
      <div className="section-heading">
        <div>
          <h2 id="policy-title">{t("ruleDetails.policy.title", { destination: destinationName })}</h2>
          <p>{t("ruleDetails.policy.intro")}</p>
        </div>
        {!open && (
          <Button
            ref={toggle}
            variant="outline"
            onClick={() => {
              setNext(current)
              update.reset()
              setOpen(true)
            }}
            aria-expanded={open}
            aria-controls="policy-form"
          >
            {t("ruleDetails.policy.change")}
          </Button>
        )}
      </div>
      {open && (
        <form id="policy-form" className="rule-edit-form" onSubmit={submit}>
          <RulePolicyFields
            idPrefix="edit-"
            policy={next}
            destination={destinationName}
            privacyRef={firstField}
            onChange={setNext}
          />
          {changed && (
            <PolicyConsequences
              detail={detail}
              current={current}
              next={next}
              widens={widens}
              destinationName={destinationName}
            />
          )}
          {update.error && <div className="inline-error" role="alert">{apiErrorMessage(i18n, update.error)}</div>}
          <PlanRestartNote state={detail.state} />
          <div className="form-actions">
            <Button type="submit" disabled={!changed || update.isPending}>
              {update.isPending
                ? t("ruleDetails.policy.saving")
                : widens
                  ? t("ruleDetails.policy.saveWidens", { destination: destinationName })
                  : t("ruleDetails.policy.save")}
            </Button>
            <Button type="button" variant="outline" onClick={cancel} disabled={update.isPending}>
              {t("ruleDetails.policy.cancel")}
            </Button>
          </div>
        </form>
      )}
    </section>
  )
}

/**
 * Beside Save, while more rules count than the User's plan allows: a policy change stops the
 * rule until it is previewed again, and the plan may then not let it start (decision 4). Only an
 * enabled or stopped rule can count, so a paused or new one gets no note.
 */
function PlanRestartNote({ state }: { state: RuleDetail["state"] }) {
  const { t } = useI18n()
  const warning = usePlanWarning()
  if (!warning || (state !== "enabled" && state !== "degraded")) return null
  return (
    <p className="field-hint" data-tone="attention">
      {t("common.plan.mayNotRestart")}
    </p>
  )
}

function PolicyConsequences({
  detail,
  current,
  next,
  widens,
  destinationName,
}: {
  detail: RuleDetail
  current: RulePolicyPayload
  next: RulePolicyPayload
  widens: boolean
  destinationName: string
}) {
  const i18n = useI18n()
  const { t } = i18n
  return (
    <div className="consequence-panel" data-tone={widens ? "attention" : undefined} role="status" aria-live="polite">
      <h3>
        {widens
          ? t("ruleDetails.policy.widensTitle", { destination: destinationName })
          : t("ruleDetails.policy.consequencesTitle")}
      </h3>
      <ul>
        {policyChangeConsequences(i18n, {
          state: detail.state,
          stopCause: detail.stop_cause,
          current,
          next,
          mappingCount: detail.mapping_count,
          destination: destinationName,
        }).map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
    </div>
  )
}
