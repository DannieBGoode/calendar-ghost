import { useMutation } from "@tanstack/react-query"
import { useRef, useState, type SyntheticEvent } from "react"

import { InvitationResponseFields } from "@/components/invitation-response-fields"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { NativeSelect } from "@/components/ui/native-select"
import { api, type RuleDetail, type RulePolicyPayload } from "@/lib/api"
import { policyChanged, policyChangeConsequences } from "@/lib/rule-change"
import { useDisclosureFocus } from "@/lib/use-disclosure-focus"
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
  const invalidate = useRuleInvalidation(detail.id)
  const toggle = useRef<HTMLButtonElement>(null)
  const firstField = useRef<HTMLSelectElement>(null)
  const current: RulePolicyPayload = {
    privacy_policy: detail.privacy_policy,
    sync_all_day_events: detail.sync_all_day_events,
    tentative_events: detail.tentative_events,
    unanswered_invitations: detail.unanswered_invitations,
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
      onSaved({ tone: "success", text: "Policy saved. Preview the rule to start syncing with the new policy." })
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
          <h2 id="policy-title">What {destinationName} shows</h2>
          <p>A change stops the rule from writing until you preview it again.</p>
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
            Change policy
          </Button>
        )}
      </div>
      {open && (
        <form id="policy-form" className="rule-edit-form" onSubmit={submit}>
          <div className="field-stack">
            <Label htmlFor="edit-privacy-policy">Event information</Label>
            <NativeSelect
              ref={firstField}
              id="edit-privacy-policy"
              value={next.privacy_policy}
              onChange={(event) =>
                setNext({ ...next, privacy_policy: event.target.value as RulePolicyPayload["privacy_policy"] })
              }
            >
              <option value="busy_only">Busy only (recommended)</option>
              <option value="copy_details">Copy title, description, and location</option>
            </NativeSelect>
          </div>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={next.sync_all_day_events}
              onChange={(event) => setNext({ ...next, sync_all_day_events: event.target.checked })}
            />
            <span>
              <strong>Sync all-day events</strong>
              <small>Turn this off to synchronize timed events only.</small>
            </span>
          </label>
          <InvitationResponseFields
            idPrefix="edit-"
            policy={next}
            onChange={(change) => setNext({ ...next, ...change })}
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
          {update.error && <div className="inline-error" role="alert">{update.error.message}</div>}
          <div className="form-actions">
            <Button type="submit" disabled={!changed || update.isPending}>
              {update.isPending ? "Saving…" : widens ? `Show event details in ${destinationName}` : "Save policy change"}
            </Button>
            <Button type="button" variant="outline" onClick={cancel} disabled={update.isPending}>
              Cancel
            </Button>
          </div>
        </form>
      )}
    </section>
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
  return (
    <div className="consequence-panel" data-tone={widens ? "attention" : undefined} role="status" aria-live="polite">
      <h3>{widens ? `Everyone who can see ${destinationName} will see event details` : "What happens when you save"}</h3>
      <ul>
        {policyChangeConsequences({
          state: detail.state,
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
