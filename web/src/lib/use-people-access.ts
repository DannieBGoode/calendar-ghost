import { useQuery } from "@tanstack/react-query"

import { api, type PendingInvitation, type Registration } from "@/lib/api"
import { isAdministrator } from "@/lib/people"

/** Whether the People page is offered: still being asked, open, or not for this User now. */
export type PeopleAccess = "pending" | "open" | "closed"

/**
 * The People page is for Installation Administrators, and only while the Registration Policy lets
 * people join, or there are other people or live Invitations to manage. Shares the session and Registration
 * Policy queries, so changing the policy in Settings shows or hides it at once.
 */
export function usePeopleAccess(): PeopleAccess {
  const session = useQuery({ queryKey: ["session"], queryFn: api.session })
  const administrator = isAdministrator(session.data?.user)
  const registration = useQuery({ queryKey: ["registration"], queryFn: api.registration, enabled: administrator })
  const needsInvitations = administrator && soleAdministrator(registration.data)
  const invitations = useQuery({ queryKey: ["invitations"], queryFn: api.invitations, enabled: needsInvitations })
  if (session.isPending) return "pending"
  if (!administrator) return "closed"
  if (registration.isPending) return "pending"
  if (needsInvitations && invitations.isPending) return "pending"
  return hasPeopleToManage(registration.data, invitations.data) ? "open" : "closed"
}

function soleAdministrator(registration: Registration | undefined): boolean {
  return registration?.policy === "only_me" && registration.only_me_available
}

function hasPeopleToManage(registration: Registration | undefined, invitations: PendingInvitation[] | undefined): boolean {
  if (!registration?.policy) return false
  if (!soleAdministrator(registration)) return true
  // The administrator API lists only unconsumed, unrevoked, unexpired Invitations.
  return Array.isArray(invitations) && invitations.length > 0
}
