import { keepPreviousData, useIsMutating, useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"

import { useI18n } from "@/i18n/provider"
import type { MessageKey } from "@/i18n/types"
import { api, type IssuedLink, type PeopleQuery, type Person, type UserDeletion } from "@/lib/api"
import { deletionMessage, personName } from "@/lib/people"
import type { PlanMoves } from "@/lib/plan-assignment"
import { OWN_PLAN_QUERY } from "@/lib/use-own-plan"
import { PLANS_QUERY } from "@/lib/use-plans"

/**
 * What an Installation Administrator can do to another User. "plan" opens Change plan beside them,
 * which then changes their Plan itself, as Plans change from Everyone.
 */
type PersonAction = "promote" | "demote" | "disable" | "enable" | "reset" | "delete" | "plan"
/** A command that is sent as it is chosen, rather than opening a next step. */
type SentAction = Exclude<PersonAction, "plan">
/** A command on someone; "delete" opens its confirmation first, and "plan" opens Change plan. */
export type PersonCommand = { person: Person; action: PersonAction }
type SentCommand = { person: Person; action: SentAction }

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

async function run({ person, action }: SentCommand): Promise<Outcome> {
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
 * beside the person it was for. `onDeleted` hears what a deletion did, for a page that cannot
 * stay once its person is gone.
 */
export function usePersonCommands({ onDeleted }: { onDeleted?: (message: string) => void } = {}) {
  const i18n = useI18n()
  const queryClient = useQueryClient()
  const [message, setMessage] = useState("")
  const [deleting, setDeleting] = useState<string | null>(null)
  // The person whose Plan is being chosen, inline beside them.
  const [choosingPlan, setChoosingPlan] = useState<string | null>(null)
  const [resetLink, setResetLink] = useState<{ personId: string; link: IssuedLink } | null>(null)
  // What the last command on someone still listed did, shown beside them.
  const [result, setResult] = useState<{ personId: string; text: string } | null>(null)
  const [deletedMessage, setDeletedMessage] = useState("")
  const busy = useIsMutating({ mutationKey: PERSON_COMMAND }) > 0
  const command = useMutation({
    mutationKey: PERSON_COMMAND,
    mutationFn: run,
    onSuccess: async (outcome, command) => {
      finish(outcome, command)
      // Whether Only Me is available depends on who is left, and each Plan's people counts
      // depend on who has it and whom it limits.
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["people"] }),
        queryClient.invalidateQueries({ queryKey: ["registration"] }),
        queryClient.invalidateQueries({ queryKey: PLANS_QUERY }),
      ])
    },
  })

  function finish({ link, deletion }: Outcome, { person, action }: SentCommand) {
    const name = personName(i18n, person)
    const changed = CHANGED[action]
    if (link) setResetLink({ personId: person.id, link })
    if (deletion) {
      const deleted = deletionMessage(i18n, name, deletion)
      setDeleting(null)
      setMessage(deleted)
      setDeletedMessage(deleted)
    }
    if (changed) {
      const text = i18n.t(changed, { email: name })
      setMessage(text)
      setResult({ personId: person.id, text })
    }
  }

  // Asks the query client rather than `busy`, so even a second click before the page shows the
  // first command running waits.
  function running(): boolean {
    return queryClient.isMutating({ mutationKey: PERSON_COMMAND }) > 0
  }

  function send(next: SentCommand) {
    if (running()) return
    // A callback given to this one call runs only while the page that sent it is still shown,
    // so a deletion that finishes after leaving it never navigates from wherever the
    // administrator went.
    command.mutate(next, {
      onSuccess: ({ deletion }) => {
        if (deletion && onDeleted) onDeleted(deletionMessage(i18n, personName(i18n, next.person), deletion))
      },
    })
  }

  function start(next: PersonCommand) {
    if (running()) return
    command.reset()
    setMessage("")
    setResult(null)
    setDeletedMessage("")
    // One next step at a time: a new command closes an open deletion or Plan choice. A shown
    // Password Reset Link stays, since it cannot be shown again.
    setDeleting(null)
    setChoosingPlan(null)
    if (next.action === "delete") setDeleting(next.person.id)
    else if (next.action === "plan") setChoosingPlan(next.person.id)
    else send({ person: next.person, action: next.action })
  }

  /** Closes Change plan, unless a change is on its way. */
  function closePlanChoice() {
    if (running()) return
    setChoosingPlan(null)
  }

  /** The error of the last command, when it was for this person. */
  function errorFor(person: Person): unknown {
    return command.variables?.person.id === person.id ? command.error : null
  }

  /** What the last command on this person did, when it was for them. */
  function resultFor(person: Person): string | null {
    return result?.personId === person.id ? result.text : null
  }

  /** Whether a command on this person has something to show beside them. */
  function hasDetails(person: Person): boolean {
    return (
      errorFor(person) !== null ||
      deleting === person.id ||
      resetLink?.personId === person.id ||
      resultFor(person) !== null
    )
  }

  return {
    command,
    busy,
    message,
    deletedMessage,
    deleting,
    setDeleting,
    choosingPlan,
    closePlanChoice,
    resetLink,
    setResetLink,
    start,
    send,
    errorFor,
    resultFor,
    hasDetails,
  }
}

export type PeopleCommands = ReturnType<typeof usePersonCommands>

/**
 * Giving Plans to people from Change plan, for one person or several, or Undo's Plan back to each,
 * in one call, all or none. It shares the person commands' key, so it and another command on
 * someone never run together, and refreshes People, each person's page, the Plans, and the
 * administrator's own Plan. A refused Plan may have been removed meanwhile, so a refusal reads the
 * Plans again.
 */
export function useGivePlans() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationKey: PERSON_COMMAND,
    mutationFn: (moves: PlanMoves) => api.assignPlans(moves, false),
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: ["people"] }),
        queryClient.invalidateQueries({ queryKey: PLANS_QUERY }),
        queryClient.invalidateQueries({ queryKey: OWN_PLAN_QUERY }),
      ]),
    onError: () => queryClient.invalidateQueries({ queryKey: PLANS_QUERY }),
  })
}

// The person whose page was opened from People, and the list's address then, so coming back
// restores the same search, filters, sort, and page. The address lasts until someone else is
// opened, so Back then Forward to their page still leads to the same list; focusing their row
// on return happens once.
let opened: { personId: string; search: string } | null = null
let focusTarget: string | null = null

/** Remember the person whose page People is about to open, and the list's search then. */
export function rememberOpenedPerson(personId: string, search: string): void {
  opened = { personId, search }
  focusTarget = personId
}

/** The list's address search to return to from this person's page; empty when opened elsewhere. */
export function peopleReturnSearch(personId: string): string {
  return opened?.personId === personId ? opened.search : ""
}

/** The person whose row People focuses on return, once; later calls answer null. */
export function takeOpenedPerson(): string | null {
  const personId = focusTarget
  focusTarget = null
  return personId
}
