import { DestructiveConfirmation } from "@/components/destructive-confirmation"
import { LinkReveal } from "@/components/link-reveal"
import { OverflowMenu, type OverflowMenuItem } from "@/components/overflow-menu"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { InvitationsList } from "@/features/settings-invitations"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import type { I18n } from "@/i18n/translator"
import type { Person } from "@/lib/api"
import { isAdministrator, personFacts, personName } from "@/lib/people"
import { passwordResetLink } from "@/lib/public-links"
import { usePeople, type PeopleCommands, type PersonCommand } from "@/lib/use-people"
import { useNow } from "@/lib/use-now"

/**
 * The Users of this installation, for an Installation Administrator: who they are and when they
 * last signed in, never what they own. Shown only while the Registration Policy lets people join.
 */
export function PeopleSection({ currentUserId }: { currentUserId: string }) {
  const { t } = useI18n()
  const now = useNow()
  const commands = usePeople()
  const { people, message } = commands
  return (
    <section className="settings-section" aria-labelledby="people-title">
      <div className="section-heading">
        <div>
          <h2 id="people-title">{t("settings.people.title")}</h2>
          <p>{t("settings.people.intro")}</p>
        </div>
      </div>
      {people.isPending && <Skeleton className="h-16 w-full" />}
      {people.error && (
        <div className="inline-error integration-load-error" role="alert">
          <span>{t("settings.people.loadError")}</span>
          <Button type="button" variant="outline" onClick={() => void people.refetch()}>
            {t("settings.people.tryAgain")}
          </Button>
        </div>
      )}
      {people.data && (
        <div className="settings-list">
          {people.data.map((person) => (
            <PersonItem
              key={person.id}
              person={person}
              you={person.id === currentUserId}
              now={now}
              commands={commands}
            />
          ))}
        </div>
      )}
      {message && <p role="status">{message}</p>}
      <InvitationsList now={now} />
    </section>
  )
}

function PersonItem({
  person,
  you,
  now,
  commands,
}: {
  person: Person
  you: boolean
  now: number
  commands: PeopleCommands
}) {
  const i18n = useI18n()
  const { t } = i18n
  const name = personName(i18n, person)
  const error = commands.errorFor(person)
  return (
    <div className="setting-item">
      <div className="setting-row person-row">
        <div>
          <h3>{name}</h3>
          <p>{personFacts(i18n, person, now)}</p>
          <PersonBadges person={person} you={you} />
        </div>
        {!you && (
          <OverflowMenu
            label={t("settings.people.actions.label", { email: name })}
            items={personActions(i18n, person, commands.start)}
          />
        )}
      </div>
      {error !== null && (
        <p className="field-error" role="alert">
          {apiErrorMessage(i18n, error)}
        </p>
      )}
      {commands.deleting === person.id && <PersonDeletion person={person} name={name} commands={commands} />}
      {commands.resetLink?.personId === person.id && (
        <LinkReveal
          title={t("settings.people.reset.title", { email: name })}
          body={t("settings.people.reset.body", { expires: i18n.format.dateTime(commands.resetLink.link.expires_at) })}
          label={t("settings.people.reset.label", { email: name })}
          link={passwordResetLink(window.location.origin, commands.resetLink.link.token)}
          onDone={() => commands.setResetLink(null)}
        />
      )}
    </div>
  )
}

function PersonBadges({ person, you }: { person: Person; you: boolean }) {
  const { t } = useI18n()
  const disabled = person.state === "disabled"
  if (!you && !isAdministrator(person) && !disabled) return null
  return (
    <div className="person-badges">
      {you && <Badge variant="outline">{t("settings.people.you")}</Badge>}
      {isAdministrator(person) && <Badge>{t("settings.people.administrator")}</Badge>}
      {disabled && <Badge variant="stopped">{t("settings.people.disabled")}</Badge>}
    </div>
  )
}

/** Someone else's commands: their role, whether they can sign in, a new password, or deletion. */
function personActions(
  { t }: I18n,
  person: Person,
  start: (command: PersonCommand) => void,
): OverflowMenuItem[] {
  const item = (id: PersonCommand["action"], label: string, description: string): OverflowMenuItem => ({
    id,
    label,
    description,
    onSelect: () => start({ person, action: id }),
  })
  return [
    isAdministrator(person)
      ? item("demote", t("settings.people.actions.removeAdministrator"), t("settings.people.actions.removeAdministratorHint"))
      : item("promote", t("settings.people.actions.makeAdministrator"), t("settings.people.actions.makeAdministratorHint")),
    person.state === "disabled"
      ? item("enable", t("settings.people.actions.enable"), t("settings.people.actions.enableHint"))
      : item("disable", t("settings.people.actions.disable"), t("settings.people.actions.disableHint")),
    item("reset", t("settings.people.actions.passwordReset"), t("settings.people.actions.passwordResetHint")),
    item("delete", t("settings.people.actions.delete"), t("settings.people.actions.deleteHint")),
  ]
}

function PersonDeletion({ person, name, commands }: { person: Person; name: string; commands: PeopleCommands }) {
  const { t } = useI18n()
  const { command } = commands
  return (
    <DestructiveConfirmation
      id={`delete-person-${person.id}`}
      title={t("settings.people.delete.title", { email: name })}
      body={t("settings.people.delete.body")}
      cancelLabel={t("settings.people.delete.keep")}
      confirmLabel={t("settings.people.delete.confirm")}
      pendingLabel={t("settings.people.delete.pending")}
      pending={command.isPending}
      onConfirm={() => command.mutate({ person, action: "delete" })}
      onCancel={() => commands.setDeleting(null)}
    />
  )
}
