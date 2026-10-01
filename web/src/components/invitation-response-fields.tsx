import { Label } from "@/components/ui/label"
import { NativeSelect } from "@/components/ui/native-select"
import type { RulePolicyPayload, TentativeEvents, UnansweredInvitations } from "@/lib/api"
import { TENTATIVE_OPTIONS, UNANSWERED_OPTIONS, tentativeHint, unansweredHint } from "@/lib/invitation-responses"

type ResponsePolicy = Pick<RulePolicyPayload, "privacy_policy" | "tentative_events" | "unanswered_invitations">

/** The two invitation response choices, shared by the rule builder and the policy editor. */
export function InvitationResponseFields({
  idPrefix,
  policy,
  onChange,
}: {
  idPrefix: string
  policy: ResponsePolicy
  onChange: (change: Pick<RulePolicyPayload, "tentative_events" | "unanswered_invitations">) => void
}) {
  const tentativeId = `${idPrefix}tentative-events`
  const unansweredId = `${idPrefix}unanswered-invitations`
  return (
    <>
      <div className="field-stack">
        <Label htmlFor={tentativeId}>Events you answered Maybe</Label>
        <NativeSelect
          id={tentativeId}
          value={policy.tentative_events}
          aria-describedby={`${tentativeId}-hint`}
          onChange={(event) =>
            onChange({
              tentative_events: event.target.value as TentativeEvents,
              unanswered_invitations: policy.unanswered_invitations,
            })
          }
        >
          {TENTATIVE_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>{option.label}</option>
          ))}
        </NativeSelect>
        <p id={`${tentativeId}-hint`} className="field-hint">{tentativeHint(policy)}</p>
      </div>
      <div className="field-stack">
        <Label htmlFor={unansweredId}>Invitations you haven't answered</Label>
        <NativeSelect
          id={unansweredId}
          value={policy.unanswered_invitations}
          aria-describedby={`${unansweredId}-hint`}
          onChange={(event) =>
            onChange({
              tentative_events: policy.tentative_events,
              unanswered_invitations: event.target.value as UnansweredInvitations,
            })
          }
        >
          {UNANSWERED_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>{option.label}</option>
          ))}
        </NativeSelect>
        <p id={`${unansweredId}-hint`} className="field-hint">{unansweredHint(policy)}</p>
      </div>
    </>
  )
}
