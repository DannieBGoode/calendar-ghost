import type { I18n } from "@/i18n/translator"
import type { Person, PersonRole, UserDeletion } from "@/lib/api"

export function isAdministrator(user: { role: PersonRole } | null | undefined): boolean {
  return user?.role === "installation_administrator"
}

/** How the People page names someone: their email, which the upgraded first User may lack. */
export function personName(i18n: I18n, person: Person): string {
  return person.email ?? i18n.t("people.noEmail")
}

/** When someone last signed in, relative to now, or that they never have. */
export function lastSignIn(i18n: I18n, person: Person, now: number): string {
  return person.last_sign_in_at ? i18n.format.relative(person.last_sign_in_at, now) : i18n.t("people.neverSignedIn")
}

/** What deleting someone did, including the events their rules wrote. */
export function deletionMessage(i18n: I18n, name: string, result: UserDeletion): string {
  const sentences = [i18n.t("people.status.deleted", { email: name })]
  if (result.deleted > 0) sentences.push(i18n.t("people.status.deletedEvents", { count: result.deleted }))
  if (result.left > 0) sentences.push(i18n.t("people.status.left", { count: result.left }))
  return sentences.join(" ")
}
