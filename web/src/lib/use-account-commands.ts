import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"

import { useI18n } from "@/i18n/provider"
import { type ConnectedAccount, api } from "@/lib/api"
import { withoutKey } from "@/lib/utils"

export type AccessCheck = Awaited<ReturnType<typeof api.verifyAccountAccess>>

/** The account confirmations, access checks, and the commands that disconnect or delete one. */
export function useAccountCommands(accounts: ConnectedAccount[] | undefined) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [confirmingAccountId, setConfirmingAccountId] = useState<string | null>(null)
  const [deletingAccountId, setDeletingAccountId] = useState<string | null>(null)
  const [statusMessage, setStatusMessage] = useState("")
  const [accessChecks, setAccessChecks] = useState<Record<string, AccessCheck>>({})
  const verifyAccess = useMutation({
    mutationFn: async (accountId: string) => ({
      accountId,
      access: await api.verifyAccountAccess(accountId),
    }),
    onSuccess: ({ accountId, access }) => {
      setAccessChecks((current) => ({ ...current, [accountId]: access }))
    },
    // A check Google refuses lapses the account; one it passes restores it and resumes rules.
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: ["accounts"] }),
        queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
        queryClient.invalidateQueries({ queryKey: ["rules"] }),
        queryClient.invalidateQueries({ queryKey: ["incidents"] }),
      ]),
  })
  const disconnect = useMutation({
    mutationFn: api.disconnectAccount,
    onSuccess: async (account) => {
      setConfirmingAccountId(null)
      setStatusMessage(t("settings.accounts.status.disconnected", { name: account.display_name }))
      setAccessChecks((current) => withoutKey(current, account.id))
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["accounts"] }),
        queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
        queryClient.invalidateQueries({ queryKey: ["rules"] }),
      ])
    },
  })
  const permanentDelete = useMutation({
    mutationFn: async (accountId: string) => {
      const account = accounts?.find((candidate) => candidate.id === accountId)
      await api.deleteAccount(accountId)
      return {
        accountId,
        displayName: account?.display_name ?? t("settings.accounts.status.unknownName"),
        ruleCount: account?.rule_count ?? 0,
      }
    },
    onSuccess: async ({ accountId, displayName, ruleCount }) => {
      setDeletingAccountId(null)
      setStatusMessage(
        ruleCount > 0
          ? t("settings.accounts.status.deletedWithRules", { name: displayName, count: ruleCount })
          : t("settings.accounts.status.deleted", { name: displayName }),
      )
      setAccessChecks((current) => withoutKey(current, accountId))
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["accounts"] }),
        queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
        queryClient.invalidateQueries({ queryKey: ["rules"] }),
        queryClient.invalidateQueries({ queryKey: ["activity"] }),
        queryClient.invalidateQueries({ queryKey: ["incidents"] }),
      ])
    },
  })

  function confirmDisconnect(accountId: string) {
    disconnect.reset()
    permanentDelete.reset()
    setStatusMessage("")
    setDeletingAccountId(null)
    setConfirmingAccountId(accountId)
  }

  function confirmPermanentDelete(accountId: string) {
    disconnect.reset()
    permanentDelete.reset()
    setStatusMessage("")
    setConfirmingAccountId(null)
    setDeletingAccountId(accountId)
  }

  function checkAccess(accountId: string) {
    verifyAccess.reset()
    setStatusMessage("")
    verifyAccess.mutate(accountId)
  }

  return {
    confirmingAccountId,
    setConfirmingAccountId,
    deletingAccountId,
    setDeletingAccountId,
    statusMessage,
    accessChecks,
    verifyAccess,
    disconnect,
    permanentDelete,
    confirmDisconnect,
    confirmPermanentDelete,
    checkAccess,
  }
}

export type AccountCommands = ReturnType<typeof useAccountCommands>
