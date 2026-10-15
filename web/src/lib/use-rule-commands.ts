import { useQueryClient } from "@tanstack/react-query"
import { useEffect, useRef, useState } from "react"

import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import type { I18n } from "@/i18n/translator"
import type { MessageKey } from "@/i18n/types"
import { api, type RuleDetail, type RuleSummary, type RunningWork } from "@/lib/api"
import {
  pausedMessage,
  reconcileResultMessage,
  syncResultMessage,
} from "@/lib/rule-run"
import { OWN_PLAN_QUERY } from "@/lib/use-own-plan"
import { withoutKey } from "@/lib/utils"

/**
 * Work a rule can be busy with. A preview runs on its own page, and starting a rule happens only
 * there, after its events were seen, so neither is run from here.
 */
export type RuleCommand = "preview" | "sync" | "reconcile" | "pause"
/** The commands this hook runs. */
export type RunnableCommand = Exclude<RuleCommand, "preview">
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

const FAILED: Record<RunnableCommand, MessageKey> = {
  sync: "ruleDetails.commands.failed.sync",
  reconcile: "ruleDetails.commands.failed.reconcile",
  pause: "ruleDetails.commands.failed.pause",
}

/**
 * Everything a rule command or change can alter. Incidents are among them: a successful run
 * resolves one, and a recovery preview can move one back to the account still to reauthorize.
 */
/**
 * A rule's preview page result, kept for the session. Any change to the rule makes it a preview
 * of something else, so changes forget it and the page previews again when next opened.
 */
export function rulePreviewKey(ruleId: string) {
  return ["rule-preview", ruleId] as const
}

export const RULE_CHANGE_QUERIES = [
  ["rules"],
  ["dashboard"],
  ["activity"],
  ["accounts"],
  ["recent-changes"],
  ["incidents"],
  // Starting, pausing, previewing, or removing a rule changes how many rules count toward the Plan.
  OWN_PLAN_QUERY,
] as const

/** What a command did, in the active language. */
async function execute(i18n: I18n, ruleId: string, command: RunnableCommand, destination: string): Promise<string> {
  switch (command) {
    case "sync":
      return syncResultMessage(i18n, await api.syncRule(ruleId))
    case "reconcile":
      return reconcileResultMessage(i18n, await api.reconcileRule(ruleId), destination)
    case "pause":
      await api.pauseRule(ruleId)
      return pausedMessage(i18n, destination)
  }
}

/**
 * Runs rule commands with per-rule pending state and feedback, so one row's work never
 * relabels another row, and every result is announced through one persistent live region.
 */
export function useRuleCommands() {
  const i18n = useI18n()
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
    setFeedback((current) => withoutKey(current, ruleId))
  }

  function notify(ruleId: string, next: RuleFeedback) {
    setFeedback((current) => ({ ...current, [ruleId]: next }))
    announce(next.text)
  }

  /**
   * `focusTarget` receives focus afterwards if the control that started the command is gone,
   * as when starting a rule replaces its own button, so keyboard focus is never stranded.
   */
  async function run(
    ruleId: string,
    command: RunnableCommand,
    destination: string,
    focusTarget?: () => HTMLElement | null,
  ) {
    const commandStartedAt = Date.now()
    setPending((current) => ({ ...current, [ruleId]: command }))
    setPendingSince((current) => ({ ...current, [ruleId]: commandStartedAt }))
    clearFeedback(ruleId)
    let completed = false
    try {
      const text = await execute(i18n, ruleId, command, destination)
      completed = true
      notify(ruleId, { tone: "success", text })
    } catch (error) {
      const failed = i18n.t(FAILED[command])
      // Two sentences: what did not happen, then why.
      const text = error instanceof Error ? `${failed} ${apiErrorMessage(i18n, error)}` : failed
      notify(ruleId, { tone: "error", text })
    } finally {
      queryClient.removeQueries({ queryKey: rulePreviewKey(ruleId) })
      // Stay pending until the refreshed rule arrives, so the row never flashes its old state.
      await Promise.all(
        [...RULE_CHANGE_QUERIES, ["rule", ruleId]].map((queryKey) => queryClient.invalidateQueries({ queryKey })),
      )
      if (completed) {
        // The command response proves this rule's work has finished. Clear stale running snapshots
        // after the refetch so a delayed or failed refresh cannot leave the spinner on screen.
        queryClient.setQueryData<RuleSummary[]>(["rules"], (rules) =>
          rules?.map((rule) =>
            rule.id === ruleId ? (clearCompletedWork(rule, command, commandStartedAt) ?? rule) : rule,
          ),
        )
        queryClient.setQueryData<RuleDetail>(["rule", ruleId], (rule) =>
          clearCompletedWork(rule, command, commandStartedAt),
        )
      }
      setPending((current) => withoutKey(current, ruleId))
      window.requestAnimationFrame(() => {
        const active = document.activeElement
        if (!active || active === document.body || !active.isConnected) focusTarget?.()?.focus()
      })
    }
  }

  return { pending, pendingSince, feedback, announcement, run, notify }
}
