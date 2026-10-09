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

/** Whether the Operator Overview shows this User to someone else: still being asked, or not. */
export type OverviewSharing = "pending" | "shared" | "alone"

/**
 * Whether anyone else is here to see what the Operator Overview shows about this User. Under Only
 * me nobody else can be; a User who does not administer is never alone, since Only me allows no
 * second User, so only an administrator asks the Registration Policy.
 */
export function useOverviewSharing(): OverviewSharing {
  const session = useQuery({ queryKey: ["session"], queryFn: api.session })
  const administrator = isAdministrator(session.data?.user)
  const registration = useQuery({ queryKey: ["registration"], queryFn: api.registration, enabled: administrator })
  if (session.isPending) return "pending"
  if (!administrator) return "shared"
  if (registration.isPending) return "pending"
  return registration.data?.policy === "only_me" ? "alone" : "shared"
}
