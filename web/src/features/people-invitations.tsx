import { GhostMark } from "@/components/ghost-mark"
import { LinkReveal } from "@/components/link-reveal"
import { Button } from "@/components/ui/button"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import type { PendingInvitation } from "@/lib/api"
import { invitationLink } from "@/lib/public-links"
import type { InvitationCommands } from "@/lib/use-invitations"

const LINK_EXPIRY: Intl.DateTimeFormatOptions = { dateStyle: "medium", timeStyle: "short" }

/**
 * People's Invitations tab: the link just created, shown once, and the invitations still waiting
 * to be used, each of which can be revoked. "Invite someone" sits in the page heading.
 */
export function InvitationsSection({ commands, now }: { commands: InvitationCommands; now: number }) {
  const i18n = useI18n()
  const { t } = i18n
  const { invitations, issued, setIssued, invite } = commands
  return (
    <section className="workflow page-card" aria-labelledby="invitations-title">
      <div className="section-heading">
        <div>
          <h2 id="invitations-title">{t("people.invitations.title")}</h2>
          <p>{t("people.invitations.body")}</p>
        </div>
      </div>
      {invite.error && (
        <p className="field-error" role="alert">
          {apiErrorMessage(i18n, invite.error)}
        </p>
      )}
      {issued && (
        <LinkReveal
          title={t("people.invitations.reveal.title")}
          body={t("people.invitations.reveal.body", { expires: i18n.format.dateTime(issued.expires_at, LINK_EXPIRY) })}
          label={t("people.invitations.reveal.label")}
          link={invitationLink(window.location.origin, issued.token)}
          onDone={() => setIssued(null)}
        />
      )}
      {invitations.data?.length === 0 && !issued && <NoInvitations />}
      {invitations.data && invitations.data.length > 0 && (
        <ul className="invitation-list">
          {invitations.data.map((invitation) => (
            <PendingInvitationItem key={invitation.id} invitation={invitation} now={now} commands={commands} />
          ))}
        </ul>
      )}
    </section>
  )
}

function NoInvitations() {
  const { t } = useI18n()
  return (
    <div className="empty-panel">
      <GhostMark className="empty-ghost" />
      <h3>{t("people.invitations.empty.title")}</h3>
      <p>{t("people.invitations.empty.body")}</p>
    </div>
  )
}

function PendingInvitationItem({
  invitation,
  now,
  commands,
}: {
  invitation: PendingInvitation
  now: number
  commands: InvitationCommands
}) {
  const i18n = useI18n()
  const { t } = i18n
  const { revoke } = commands
  const expires = i18n.format.relative(invitation.expires_at, now)
  const failed = revoke.error && revoke.variables === invitation.id
  return (
    <li className="invitation-item">
      <div className="setting-row">
        <div>
          <h3>{t("people.invitations.expiresIn", { relative: expires })}</h3>
          <p>
            <time dateTime={invitation.created_at} title={i18n.format.dateTime(invitation.created_at, LINK_EXPIRY)}>
              {t("people.invitations.createdAgo", { relative: i18n.format.relative(invitation.created_at, now) })}
            </time>
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          aria-label={t("people.invitations.revokeLabel", { expires })}
          disabled={revoke.isPending}
          onClick={() => revoke.mutate(invitation.id)}
        >
          {t("people.invitations.revoke")}
        </Button>
      </div>
      {failed && (
        <p className="field-error" role="alert">
          {apiErrorMessage(i18n, revoke.error)}
        </p>
      )}
    </li>
  )
}
