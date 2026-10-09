import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useRef, useState } from "react"

import { useI18n } from "@/i18n/provider"
import { api, type IntegrationToken, type IssuedIntegrationToken } from "@/lib/api"
import { tokenScopes } from "@/lib/integrations"
import { useCopyState } from "@/lib/use-copy-state"

export type { CopyState } from "@/lib/use-copy-state"

/** The Integration Tokens list, the token issued this visit, and the commands that issue or revoke one. */
export function useIntegrationTokens() {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const tokens = useQuery({ queryKey: ["integration-tokens"], queryFn: api.integrationTokens })
  const [name, setName] = useState("")
  // Only an Installation Administrator is offered this; it is off for every new token.
  const [installation, setInstallation] = useState(false)
  const [issued, setIssued] = useState<IssuedIntegrationToken | null>(null)
  const [revoking, setRevoking] = useState<string | null>(null)
  const [copyState, setCopyState] = useCopyState()
  const [message, setMessage] = useState("")
  const summaryButton = useRef<HTMLButtonElement>(null)
  const issue = useMutation({
    mutationFn: () => api.issueIntegrationToken(name, tokenScopes(installation)),
    onSuccess: async (token) => {
      setIssued(token)
      setName("")
      setInstallation(false)
      setCopyState("idle")
      // Announce the issue, never the token: a screen reader would read the secret aloud.
      setMessage(t("settings.integrations.status.issued", { name: token.name }))
      await queryClient.invalidateQueries({ queryKey: ["integration-tokens"] })
    },
  })
  const revoke = useMutation({
    mutationFn: (token: IntegrationToken) => api.revokeIntegrationToken(token.id),
    onSuccess: async (_result, token) => {
      setRevoking(null)
      // The plaintext token lives only in this component's state, shown once; if the admin
      // revokes it right away, stop showing a secret that no longer works.
      setIssued((current) => (current?.id === token.id ? null : current))
      setMessage(t("settings.integrations.status.revoked", { name: token.name }))
      await queryClient.invalidateQueries({ queryKey: ["integration-tokens"] })
      // The revoked row loses its button, so focus returns to the group it belongs to.
      summaryButton.current?.focus()
    },
  })

  function finishReveal() {
    setIssued(null)
    setCopyState("idle")
    setMessage("")
  }

  return {
    tokens,
    name,
    setName,
    installation,
    setInstallation,
    issued,
    revoking,
    setRevoking,
    copyState,
    setCopyState,
    message,
    summaryButton,
    issue,
    revoke,
    finishReveal,
  }
}

export type IntegrationTokens = ReturnType<typeof useIntegrationTokens>
