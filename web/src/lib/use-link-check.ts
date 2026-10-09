import { useQuery } from "@tanstack/react-query"
import { useState } from "react"

import { api } from "@/lib/api"
import { linkStatus, linkToken, type PublicPage } from "@/lib/public-links"

const CHECKS: Record<PublicPage, (token: string) => Promise<{ usable: boolean }>> = {
  invitation: (token) => api.checkInvitation(token),
  "password-reset": (token) => api.checkPasswordReset(token),
}

/**
 * The token in this page's address and whether the server will still accept it. An address
 * without a token is refused without asking the server.
 */
export function useLinkCheck(page: PublicPage) {
  const [token] = useState(() => linkToken(window.location.hash))
  const check = useQuery({
    queryKey: ["link-check", page, token],
    queryFn: () => CHECKS[page](token),
    enabled: token !== "",
    staleTime: Infinity,
  })
  return { token, status: linkStatus(token, check), error: check.error }
}
