import { useMutation, useQueryClient } from "@tanstack/react-query"
import { LoaderCircle, Trash2 } from "lucide-react"
import { useEffect, useRef, useState, type RefObject } from "react"

import { Button } from "@/components/ui/button"
import { ProjectionChoice } from "@/features/projection-choice"
import { ApiError, api, type ProjectionHandling, type RuleDetail, type RuleSummary } from "@/lib/api"
import { isViewingRule } from "@/lib/navigation"
import {
  plural,
  removalConfirmLabel,
  removalOutcome,
  removalOutcomeUnknown,
  type RemovalOutcome,
} from "@/lib/rule-change"
import {
  elapsedLabel,
  removalErrorMessage,
  removalMutationKey,
  removalProgress,
  reportedRemoval,
  useActiveRemoval,
  type ActiveRemoval,
  type RemovalRequest,
} from "@/lib/rule-removal"
import { useDisclosureFocus } from "@/lib/use-disclosure-focus"
import { useNow } from "@/lib/use-now"
import { useRuleExit, useRuleInvalidation } from "@/lib/use-rule-refresh"

export function RuleRemoval({
  detail,
  destinationName,
  destinationConnected,
  onRemoved,
}: {
  detail: RuleDetail
  destinationName: string
  destinationConnected: boolean
  onRemoved: (outcome: RemovalOutcome) => void
}) {
  const invalidate = useRuleInvalidation(detail.id)
  const leave = useRuleExit(detail.id)
  const queryClient = useQueryClient()
  const returnFocus = useRef<HTMLButtonElement>(null)
  const firstField = useRef<HTMLInputElement>(null)
  const confirm = useRef<HTMLButtonElement>(null)
  const progress = useRef<HTMLDivElement>(null)
  const sessionRemoval = useActiveRemoval(detail.id)
  // The service's report outlives a reload; this session's request covers the moment before it.
  const active = reportedRemoval(detail.running, detail.mapping_count) ?? sessionRemoval
  const interrupted = detail.state === "disabled" && !active
  const [open, setOpen] = useState(false)
  const expanded = open || interrupted
  const [handling, setHandling] = useState<ProjectionHandling>("delete")
  useDisclosureFocus(open && !interrupted && !active, firstField, returnFocus)
  const effective: ProjectionHandling = destinationConnected ? handling : "detach"
  const finish = async (outcome: RemovalOutcome) => {
    // Update the cached list first so the removed rule never flashes back into view.
    queryClient.setQueryData<RuleSummary[]>(["rules"], (rules) => rules?.filter((rule) => rule.id !== detail.id))
    // The removal outlives this view; only take the administrator to the rules list if they
    // are still watching it. Activity keeps the outcome either way.
    if (isViewingRule(detail.id)) onRemoved(outcome)
    await leave()
  }
  const remove = useMutation({
    mutationKey: removalMutationKey(detail.id),
    mutationFn: (request: RemovalRequest) => api.removeRule(detail.id, request.handling),
    onSuccess: (result) => finish(removalOutcome(result, destinationName)),
    onError: async (error) => {
      // A retry that waited behind an earlier, successful attempt finds the rule already gone;
      // that attempt's counts are lost, so say what to check instead of claiming none.
      if (error instanceof ApiError && error.status === 404) {
        await finish(removalOutcomeUnknown(destinationName))
        return
      }
      await invalidate()
    },
  })
  // The confirming button leaves the page while removal runs, so keep focus on its progress.
  useEffect(() => {
    if (active) progress.current?.focus()
  }, [active])
  useEffect(() => {
    if (remove.error) confirm.current?.focus()
  }, [remove.error])

  return (
    <section className="rule-section page-card rule-removal" aria-labelledby="removal-title" aria-busy={active ? true : undefined}>
      <RemovalHeading
        toggle={returnFocus}
        active={active !== undefined}
        interrupted={interrupted}
        expanded={expanded}
        mappingCount={detail.mapping_count}
        onOpen={() => setOpen(true)}
      />
      {active ? (
        <RemovalProgress
          ref={progress}
          request={active}
          remaining={detail.mapping_count}
          destinationName={destinationName}
        />
      ) : (
        expanded && (
          <RemovalForm
            detail={detail}
            effective={effective}
            firstField={firstField}
            confirm={confirm}
            destinationName={destinationName}
            destinationConnected={destinationConnected}
            interrupted={interrupted}
            error={remove.error}
            onHandling={setHandling}
            onRemove={() => remove.mutate({ handling: effective, total: detail.mapping_count })}
            onKeep={() => setOpen(false)}
          />
        )
      )}
    </section>
  )
}

function RemovalHeading({
  toggle,
  active,
  interrupted,
  expanded,
  mappingCount,
  onOpen,
}: {
  toggle: RefObject<HTMLButtonElement | null>
  active: boolean
  interrupted: boolean
  expanded: boolean
  mappingCount: number
  onOpen: () => void
}) {
  return (
    <div className="section-heading">
      <div>
        <h2 id="removal-title">
          {active ? "Removing rule" : interrupted ? "Removal incomplete" : "Remove rule"}
        </h2>
        <p>
          {active
            ? "The rule no longer synchronizes. Source events are never changed. Removal continues if you leave this page."
            : interrupted
              ? `Removal stopped with ${plural(mappingCount, "projection")} left. Retry to finish; the rule does not synchronize meanwhile.`
              : "Removing a rule is permanent. Source events are never changed."}
        </p>
      </div>
      {!expanded && !active && (
        <Button
          ref={toggle}
          variant="outline"
          className="removal-toggle"
          onClick={onOpen}
          aria-expanded={expanded}
          aria-controls="removal-form"
        >
          <Trash2 aria-hidden="true" /> Remove rule…
        </Button>
      )}
    </div>
  )
}

function RemovalForm({
  detail,
  effective,
  firstField,
  confirm,
  destinationName,
  destinationConnected,
  interrupted,
  error,
  onHandling,
  onRemove,
  onKeep,
}: {
  detail: RuleDetail
  effective: ProjectionHandling
  firstField: RefObject<HTMLInputElement | null>
  confirm: RefObject<HTMLButtonElement | null>
  destinationName: string
  destinationConnected: boolean
  interrupted: boolean
  error: Error | null
  onHandling: (value: ProjectionHandling) => void
  onRemove: () => void
  onKeep: () => void
}) {
  return (
    <div id="removal-form" className="rule-edit-form removal-form">
      <ProjectionChoice
        name="removal-projections"
        value={effective}
        onChange={onHandling}
        firstField={firstField}
        mappingCount={detail.mapping_count}
        destinationName={destinationName}
        deleteAvailable={destinationConnected}
      />
      <div className="form-actions">
        <Button ref={confirm} variant="destructive" onClick={onRemove}>
          <Trash2 aria-hidden="true" />
          {interrupted ? "Retry removal" : removalConfirmLabel(effective, detail.mapping_count)}
        </Button>
        {!interrupted && (
          <Button variant="outline" onClick={onKeep}>
            Keep rule
          </Button>
        )}
      </div>
      {error && <div className="inline-error" role="alert">{removalErrorMessage(error)}</div>}
    </div>
  )
}

function RemovalProgress({
  ref,
  request,
  remaining,
  destinationName,
}: {
  ref: RefObject<HTMLDivElement | null>
  request: ActiveRemoval
  remaining: number
  destinationName: string
}) {
  const now = useNow(1_000)
  const { done, label } = removalProgress(request, remaining, destinationName)
  return (
    <div ref={ref} tabIndex={-1} className="removal-progress">
      <p className="removal-progress-label">
        <LoaderCircle aria-hidden="true" className="work-spinner" />
        <span>{label}</span>
      </p>
      {done !== null && (
        <progress className="removal-bar" value={done} max={request.total} aria-label={label} />
      )}
      <p className="removal-progress-meta">Running for {elapsedLabel(now - request.startedAt)}</p>
    </div>
  )
}
