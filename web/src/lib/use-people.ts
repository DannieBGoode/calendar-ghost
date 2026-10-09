import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"

import { useI18n } from "@/i18n/provider"
import type { MessageKey } from "@/i18n/types"
import { api, type IssuedLink, type Person, type UserDeletion } from "@/lib/api"
import { deletionMessage, personName } from "@/lib/people"

/** What an Installation Administrator can do to another User. */
export type PersonAction = "promote" | "demote" | "disable" | "enable" | "reset" | "delete"
export type PersonCommand = { person: Person; action: PersonAction }

/** What a command returned that the administrator needs next: a link to pass on, or a deletion's counts. */
type Outcome = { link?: IssuedLink; deletion?: UserDeletion }

const CHANGED: Partial<Record<PersonAction, MessageKey>> = {
  promote: "settings.people.status.administrator",
  demote: "settings.people.status.notAdministrator",
  disable: "settings.people.status.disabled",
  enable: "settings.people.status.enabled",
}

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

/**
 * The people list and the commands an administrator runs on someone else. One command runs at a
 * time; its error is shown beside the person it was for.
 */
export function usePeople() {
  const i18n = useI18n()
  const queryClient = useQueryClient()
  const people = useQuery({ queryKey: ["people"], queryFn: api.people })
  const [message, setMessage] = useState("")
  const [deleting, setDeleting] = useState<string | null>(null)
  const [resetLink, setResetLink] = useState<{ personId: string; link: IssuedLink } | null>(null)
  const command = useMutation({
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

  function start(next: PersonCommand) {
    command.reset()
    setMessage("")
    if (next.action === "delete") setDeleting(next.person.id)
    else command.mutate(next)
  }

  /** The error of the last command, when it was for this person. */
  function errorFor(person: Person): unknown {
    return command.variables?.person.id === person.id ? command.error : null
  }

  return { people, command, message, deleting, setDeleting, resetLink, setResetLink, start, errorFor }
}

export type PeopleCommands = ReturnType<typeof usePeople>
