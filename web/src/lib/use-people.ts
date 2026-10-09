import { keepPreviousData, useIsMutating, useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"

import { useI18n } from "@/i18n/provider"
import type { MessageKey } from "@/i18n/types"
import { api, type IssuedLink, type PeopleQuery, type Person, type UserDeletion } from "@/lib/api"
import { deletionMessage, personName } from "@/lib/people"

/** What an Installation Administrator can do to another User. */
export type PersonAction = "promote" | "demote" | "disable" | "enable" | "reset" | "delete"
export type PersonCommand = { person: Person; action: PersonAction }

/** What a command returned that the administrator needs next: a link to pass on, or a deletion's counts. */
type Outcome = { link?: IssuedLink; deletion?: UserDeletion }

const CHANGED: Partial<Record<PersonAction, MessageKey>> = {
  promote: "people.status.administrator",
  demote: "people.status.notAdministrator",
  disable: "people.status.disabled",
  enable: "people.status.enabled",
}

// Every person command shares this key, so the query client, which outlives the People page,
// knows one is running even after the page that sent it is gone.
const PERSON_COMMAND = ["person-command"]

async function run({ person, action }: PersonCommand): Promise<Outcome> {
  switch (action) {
    case "promote":
      await api.setPersonRole(person.id, "installation_administrator")
      return {}
    case "demote":
      await api.setPersonRole(person.id, "user")
      return {}
    case "disable":
      await api.setPersonState(person.id, "disabled")
      return {}
    case "enable":
      await api.setPersonState(person.id, "active")
      return {}
    case "reset":
      return { link: await api.issuePasswordResetLink(person.id) }
    case "delete":
      return { deletion: await api.deletePerson(person.id) }
  }
}

/** One page of the people matching a query; the page shown stays while the next one loads. */
export function usePeoplePage(query: PeopleQuery) {
  return useQuery({
    queryKey: ["people", query],
    queryFn: () => api.people(query),
    placeholderData: keepPreviousData,
  })
}

/**
 * The commands an administrator runs on someone else. One command runs at a time, even across
 * opening the page again: a second one started before the first answers could undo what the
 * first returned, as a new Password Reset Link revokes the one just shown. Its error is shown
 * beside the person it was for.
 */
export function usePersonCommands() {
  const i18n = useI18n()
  const queryClient = useQueryClient()
  const [message, setMessage] = useState("")
  const [deleting, setDeleting] = useState<string | null>(null)
  const [resetLink, setResetLink] = useState<{ personId: string; link: IssuedLink } | null>(null)
  const busy = useIsMutating({ mutationKey: PERSON_COMMAND }) > 0
  const command = useMutation({
    mutationKey: PERSON_COMMAND,
    mutationFn: run,
    onSuccess: async (outcome, command) => {
      finish(outcome, command)
      // Whether Only Me is available depends on who is left.
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["people"] }),
        queryClient.invalidateQueries({ queryKey: ["registration"] }),
      ])
    },
  })

  function finish({ link, deletion }: Outcome, { person, action }: PersonCommand) {
    const name = personName(i18n, person)
    const changed = CHANGED[action]
    if (link) setResetLink({ personId: person.id, link })
    if (deletion) {
      setDeleting(null)
      setMessage(deletionMessage(i18n, name, deletion))
    }
    if (changed) setMessage(i18n.t(changed, { email: name }))
  }

  // Asks the query client rather than `busy`, so even a second click before the page shows the
  // first command running waits.
  function running(): boolean {
    return queryClient.isMutating({ mutationKey: PERSON_COMMAND }) > 0
  }

  function send(next: PersonCommand) {
    if (!running()) command.mutate(next)
  }

  function start(next: PersonCommand) {
    if (running()) return
    command.reset()
    setMessage("")
    if (next.action === "delete") setDeleting(next.person.id)
    else send(next)
  }

  /** The error of the last command, when it was for this person. */
  function errorFor(person: Person): unknown {
    return command.variables?.person.id === person.id ? command.error : null
  }

  /** Whether a command on this person has something to show beside them. */
  function hasDetails(person: Person): boolean {
    return errorFor(person) !== null || deleting === person.id || resetLink?.personId === person.id
  }

  return { command, busy, message, deleting, setDeleting, resetLink, setResetLink, start, send, errorFor, hasDetails }
}

export type PeopleCommands = ReturnType<typeof usePersonCommands>
