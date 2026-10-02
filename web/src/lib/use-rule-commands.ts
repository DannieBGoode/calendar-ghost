import { useQueryClient } from "@tanstack/react-query"
import { useEffect, useRef, useState } from "react"

import { api, type RuleDetail, type RuleSummary, type RunningWork } from "@/lib/api"
import { previewSummary } from "@/lib/rule-preview"
import {
  enabledMessage,
  pausedMessage,
  reconcileResultMessage,
  syncResultMessage,
} from "@/lib/rule-run"

export type RuleCommand = "preview" | "enable" | "sync" | "reconcile" | "pause"
export type RuleFeedback = { tone: "success" | "error"; text: string }

const COMMAND_WORK: Partial<Record<RuleCommand, RunningWork["kind"]>> = {
  preview: "preview",
  sync: "sync",
  reconcile: "reconciliation",
}

/** A successful command has finished the work that a cached rule response may still report. */
export function clearCompletedWork<T extends { running: RunningWork | null }>(
  rule: T | undefined,
  command: RuleCommand,
  commandStartedAt: number,
): T | undefined {
  if (!rule || (rule.running && COMMAND_WORK[command] !== rule.running.kind)) return rule
  if (rule.running) {
    const runningStartedAt = Date.parse(rule.running.started_at)
    if (!Number.isFinite(runningStartedAt) || runningStartedAt > commandStartedAt) return rule
  }
  return { ...rule, running: null }
}

const FAILED: Record<RuleCommand, string> = {
  preview: "Preview did not complete.",
  enable: "The rule was not enabled.",
  sync: "Sync did not complete.",
  reconcile: "Reconciliation did not complete.",
  pause: "The rule was not paused.",
}

/**
 * Everything a rule command or change can alter. Incidents are among them: a successful run
 * resolves one, and a recovery preview can move one back to the account still to reauthorize.
 */
export const RULE_CHANGE_QUERIES = [
  ["rules"],
  ["dashboard"],
  ["activity"],
  ["accounts"],
  ["recent-changes"],
  ["incidents"],
] as const

export const PENDING_LABELS: Record<RuleCommand, string> = {
  preview: "Previewing…",
  enable: "Enabling…",
  sync: "Syncing…",
  reconcile: "Reconciling…",
  pause: "Pausing…",
}

/**
 * Runs rule commands with per-rule pending state and feedback, so one row's work never
 * relabels another row, and every result is announced through one persistent live region.
 */
export function useRuleCommands() {
  const queryClient = useQueryClient()
  const [pending, setPending] = useState<Record<string, RuleCommand>>({})
  const [pendingSince, setPendingSince] = useState<Record<string, number>>({})
  const [feedback, setFeedback] = useState<Record<string, RuleFeedback>>({})
  const [announcement, setAnnouncement] = useState("")
  const announceTimer = useRef<number | undefined>(undefined)

  useEffect(() => () => window.clearTimeout(announceTimer.current), [])

  function announce(text: string) {
    // Clearing first makes screen readers repeat an identical message.
    setAnnouncement("")
    window.clearTimeout(announceTimer.current)
    announceTimer.current = window.setTimeout(() => setAnnouncement(text), 60)
  }

  function clearFeedback(ruleId: string) {
    setFeedback((current) => {
      const next = { ...current }
      delete next[ruleId]
      return next
    })
  }

  function notify(ruleId: string, next: RuleFeedback) {
    setFeedback((current) => ({ ...current, [ruleId]: next }))
    announce(next.text)
  }

  async function execute(ruleId: string, command: RuleCommand, destination: string): Promise<string> {
    switch (command) {
      case "preview":
        return previewSummary(await api.previewRule(ruleId))
      case "enable":
        await api.enableRule(ruleId)
        return enabledMessage(destination)
      case "sync":
        return syncResultMessage(await api.syncRule(ruleId))
      case "reconcile":
        return reconcileResultMessage(await api.reconcileRule(ruleId), destination)
      case "pause":
        await api.pauseRule(ruleId)
        return pausedMessage(destination)
    }
  }

  /**
   * `focusTarget` receives focus afterwards if the control that started the command is gone,
   * as when a successful preview replaces its own button, so keyboard focus is never stranded.
   */
  async function run(
    ruleId: string,
    command: RuleCommand,
    destination: string,
    focusTarget?: () => HTMLElement | null,
  ) {
    const commandStartedAt = Date.now()
    setPending((current) => ({ ...current, [ruleId]: command }))
    setPendingSince((current) => ({ ...current, [ruleId]: commandStartedAt }))
    clearFeedback(ruleId)
    let completed = false
    try {
      const text = await execute(ruleId, command, destination)
      completed = true
      // A passed preview shows its result in the review that replaces the Preview button.
      if (command === "preview") announce(text)
      else notify(ruleId, { tone: "success", text })
    } catch (error) {
      const reason = error instanceof Error ? ` ${error.message}` : ""
      notify(ruleId, { tone: "error", text: `${FAILED[command]}${reason}` })
    } finally {
      // Stay pending until the refreshed rule arrives, so the row never flashes its old state.
      await Promise.all(
        [...RULE_CHANGE_QUERIES, ["rule", ruleId]].map((queryKey) => queryClient.invalidateQueries({ queryKey })),
      )
      if (completed) {
        // The command response proves this rule's work has finished. Clear stale running snapshots
        // after the refetch so a delayed or failed refresh cannot leave the spinner on screen.
        queryClient.setQueryData<RuleSummary[]>(["rules"], (rules) =>
          rules?.map((rule) =>
            rule.id === ruleId ? clearCompletedWork(rule, command, commandStartedAt)! : rule,
          ),
        )
        queryClient.setQueryData<RuleDetail>(["rule", ruleId], (rule) =>
          clearCompletedWork(rule, command, commandStartedAt),
        )
      }
      setPending((current) => {
        const next = { ...current }
        delete next[ruleId]
        return next
      })
      window.requestAnimationFrame(() => {
        const active = document.activeElement
        if (!active || active === document.body || !active.isConnected) focusTarget?.()?.focus()
      })
    }
  }

  return { pending, pendingSince, feedback, announcement, run, notify }
}
