import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useRef, useState } from "react"

import { api, type IntegrationToken, type IssuedIntegrationToken } from "@/lib/api"

// How long the Copy button says "Copied" before it offers to copy again.
const COPIED_FOR_MS = 2000

export type CopyState = "idle" | "copied" | "unavailable"

/** The Integration Tokens list, the token issued this visit, and the commands that issue or revoke one. */
export function useIntegrationTokens() {
  const queryClient = useQueryClient()
  const tokens = useQuery({ queryKey: ["integration-tokens"], queryFn: api.integrationTokens })
  const [name, setName] = useState("")
  const [issued, setIssued] = useState<IssuedIntegrationToken | null>(null)
  const [revoking, setRevoking] = useState<string | null>(null)
  const [copyState, setCopyState] = useState<CopyState>("idle")
  const [message, setMessage] = useState("")
  const summaryButton = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (copyState !== "copied") return
    const timer = window.setTimeout(() => setCopyState("idle"), COPIED_FOR_MS)
    return () => window.clearTimeout(timer)
  }, [copyState])
  const issue = useMutation({
    mutationFn: () => api.issueIntegrationToken(name),
    onSuccess: async (token) => {
      setIssued(token)
      setName("")
      setCopyState("idle")
      // Announce the issue, never the token: a screen reader would read the secret aloud.
      setMessage(`Token for ${token.name} issued. Copy it now; it is shown only once.`)
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
      setMessage(`${token.name} was revoked. Anything that used it has lost access.`)
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
