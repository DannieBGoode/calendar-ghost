import { useQuery } from "@tanstack/react-query"

import { api } from "@/lib/api"
import { isAdministrator } from "@/lib/people"

/** Whether the People page is offered: still being asked, open, or not for this User now. */
export type PeopleAccess = "pending" | "open" | "closed"

/**
 * The People page is for Installation Administrators, and only while the Registration Policy lets
 * people join: under Only me there is nobody else to manage. Shares the session and Registration
 * Policy queries, so changing the policy in Settings shows or hides it at once.
 */
export function usePeopleAccess(): PeopleAccess {
  const session = useQuery({ queryKey: ["session"], queryFn: api.session })
  const administrator = isAdministrator(session.data?.user)
  const registration = useQuery({ queryKey: ["registration"], queryFn: api.registration, enabled: administrator })
  if (session.isPending) return "pending"
  if (!administrator) return "closed"
  if (registration.isPending) return "pending"
  const policy = registration.data?.policy
  return policy === undefined || policy === "only_me" ? "closed" : "open"
}
