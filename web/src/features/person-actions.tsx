import { DestructiveConfirmation } from "@/components/destructive-confirmation"
import { LinkReveal } from "@/components/link-reveal"
import { OverflowMenu, type OverflowMenuItem } from "@/components/overflow-menu"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import type { I18n } from "@/i18n/translator"
import type { Person } from "@/lib/api"
import { isAdministrator } from "@/lib/people"
import { passwordResetLink } from "@/lib/public-links"
import type { PeopleCommands, PersonCommand } from "@/lib/use-people"

/** The menu of what an administrator can do to someone else. */
export function PersonMenu({ person, name, commands }: { person: Person; name: string; commands: PeopleCommands }) {
  const i18n = useI18n()
  return (
    <OverflowMenu
      label={i18n.t("people.actions.label", { email: name })}
      items={personActions(i18n, person, commands)}
    />
  )
}

/**
 * Someone else's commands: their role, whether they can sign in, a new password, or deletion.
 * They wait while any command runs.
 */
function personActions({ t }: I18n, person: Person, { command, start }: PeopleCommands): OverflowMenuItem[] {
  const item = (id: PersonCommand["action"], label: string, description: string): OverflowMenuItem => ({
    id,
    label,
    description,
    disabled: command.isPending,
    onSelect: () => start({ person, action: id }),
  })
  return [
    isAdministrator(person)
      ? item("demote", t("people.actions.removeAdministrator"), t("people.actions.removeAdministratorHint"))
      : item("promote", t("people.actions.makeAdministrator"), t("people.actions.makeAdministratorHint")),
    person.state === "disabled"
      ? item("enable", t("people.actions.enable"), t("people.actions.enableHint"))
      : item("disable", t("people.actions.disable"), t("people.actions.disableHint")),
    item("reset", t("people.actions.passwordReset"), t("people.actions.passwordResetHint")),
    item("delete", t("people.actions.delete"), t("people.actions.deleteHint")),
  ]
}

/** What a command on this person shows beside them: its error, the deletion to confirm, or a link. */
export function PersonDetails({ person, name, commands }: { person: Person; name: string; commands: PeopleCommands }) {
  const i18n = useI18n()
  const { t } = i18n
  const error = commands.errorFor(person)
  return (
    <>
      {error !== null && (
        <p className="field-error" role="alert">
          {apiErrorMessage(i18n, error)}
        </p>
      )}
      {commands.deleting === person.id && <PersonDeletion person={person} name={name} commands={commands} />}
      {commands.resetLink?.personId === person.id && (
        <LinkReveal
          title={t("people.reset.title", { email: name })}
          body={t("people.reset.body", { expires: i18n.format.dateTime(commands.resetLink.link.expires_at) })}
          label={t("people.reset.label", { email: name })}
          link={passwordResetLink(window.location.origin, commands.resetLink.link.token)}
          onDone={() => commands.setResetLink(null)}
        />
      )}
    </>
  )
}

function PersonDeletion({ person, name, commands }: { person: Person; name: string; commands: PeopleCommands }) {
  const { t } = useI18n()
  const { command } = commands
  return (
    <DestructiveConfirmation
      id={`delete-person-${person.id}`}
      title={t("people.delete.title", { email: name })}
      body={t("people.delete.body")}
      cancelLabel={t("people.delete.keep")}
      confirmLabel={t("people.delete.confirm")}
      pendingLabel={t("people.delete.pending")}
      pending={command.isPending}
      onConfirm={() => commands.send({ person, action: "delete" })}
      onCancel={() => commands.setDeleting(null)}
    />
  )
}
