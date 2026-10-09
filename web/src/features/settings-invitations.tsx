import { UserPlus } from "lucide-react"

import { LinkReveal } from "@/components/link-reveal"
import { Button } from "@/components/ui/button"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import type { PendingInvitation } from "@/lib/api"
import { invitationLink } from "@/lib/public-links"
import { useInvitations, type InvitationCommands } from "@/lib/use-invitations"

/**
 * Invitations: a link the administrator creates and passes on themself, shown once, and the ones
 * still waiting to be used, each of which can be revoked.
 */
export function InvitationsList({ now }: { now: number }) {
  const i18n = useI18n()
  const { t } = i18n
  const commands = useInvitations()
  const { invitations, issued, setIssued, invite, message } = commands
  return (
    <div className="settings-list">
      <div className="setting-item">
        <div className="setting-row">
          <div>
            <h3>{t("settings.invitations.title")}</h3>
            <p>{t("settings.invitations.body")}</p>
          </div>
          <Button id="invite-someone" type="button" disabled={invite.isPending} onClick={() => invite.mutate()}>
            <UserPlus aria-hidden="true" />
            {invite.isPending ? t("settings.invitations.inviting") : t("settings.invitations.invite")}
          </Button>
        </div>
        {invite.error && (
          <p className="field-error" role="alert">
            {apiErrorMessage(i18n, invite.error)}
          </p>
        )}
        {issued && (
          <LinkReveal
            title={t("settings.invitations.reveal.title")}
            body={t("settings.invitations.reveal.body", { expires: i18n.format.dateTime(issued.expires_at) })}
            label={t("settings.invitations.reveal.label")}
            link={invitationLink(window.location.origin, issued.token)}
            onDone={() => setIssued(null)}
          />
        )}
      </div>
      {invitations.data?.map((invitation) => (
        <PendingInvitationItem key={invitation.id} invitation={invitation} now={now} commands={commands} />
      ))}
      {invitations.data?.length === 0 && (
        <div className="setting-item">
          <p className="empty-line setting-row">{t("settings.invitations.none")}</p>
        </div>
      )}
      {message && <p role="status">{message}</p>}
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
  const created = i18n.format.relative(invitation.created_at, now)
  const failed = revoke.error && revoke.variables === invitation.id
  return (
    <div className="setting-item">
      <div className="setting-row">
        <div>
          <h3>{t("settings.invitations.created", { created })}</h3>
          <p>{t("settings.invitations.expires", { expires: i18n.format.dateTime(invitation.expires_at) })}</p>
        </div>
        <Button
          type="button"
          variant="outline"
          aria-label={t("settings.invitations.revokeLabel", { created })}
          disabled={revoke.isPending}
          onClick={() => revoke.mutate(invitation.id)}
        >
          {t("settings.invitations.revoke")}
        </Button>
      </div>
      {failed && (
        <p className="field-error" role="alert">
          {apiErrorMessage(i18n, revoke.error)}
        </p>
      )}
    </div>
  )
}
