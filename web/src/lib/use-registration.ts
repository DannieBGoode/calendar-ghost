import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"

import { useI18n } from "@/i18n/provider"
import type { MessageKey } from "@/i18n/types"
import { api, type RegistrationPolicy } from "@/lib/api"

const SAVED: Record<RegistrationPolicy, MessageKey> = {
  only_me: "settings.registration.saved.onlyMe",
  invitation_only: "settings.registration.saved.invitationOnly",
  open: "settings.registration.saved.open",
}

/** The Registration Policy and the command that changes it; for Installation Administrators only. */
export function useRegistration() {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const registration = useQuery({ queryKey: ["registration"], queryFn: api.registration })
  const [message, setMessage] = useState("")
  const change = useMutation({
    mutationFn: (policy: RegistrationPolicy) => api.setRegistrationPolicy(policy),
    onSuccess: (result, policy) => {
      queryClient.setQueryData(["registration"], result)
      setMessage(t(SAVED[policy]))
    },
  })
  return { registration, change, message }
}

export type RegistrationCommands = ReturnType<typeof useRegistration>
