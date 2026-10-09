import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"

import { useI18n } from "@/i18n/provider"
import { api, type IssuedLink } from "@/lib/api"

/** Pending Invitations, the one created this visit, and the commands that create or revoke one. */
export function useInvitations() {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const invitations = useQuery({ queryKey: ["invitations"], queryFn: api.invitations })
  const [issued, setIssued] = useState<IssuedLink | null>(null)
  const [message, setMessage] = useState("")
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["invitations"] })
  const invite = useMutation({
    mutationFn: () => api.invite(),
    onSuccess: async (link) => {
      setIssued(link)
      setMessage("")
      await refresh()
    },
  })
  const revoke = useMutation({
    mutationFn: (invitationId: string) => api.revokeInvitation(invitationId),
    onSuccess: async (_result, invitationId) => {
      // A revoked link must not stay on screen as if it still worked.
      setIssued((current) => (current?.id === invitationId ? null : current))
      setMessage(t("settings.invitations.revoked"))
      await refresh()
    },
  })
  return { invitations, issued, setIssued, message, invite, revoke }
}

export type InvitationCommands = ReturnType<typeof useInvitations>
