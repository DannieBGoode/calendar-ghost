import { useMutation, useQueryClient } from "@tanstack/react-query"

import { LearnWhyLink } from "@/components/learn-why-link"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import { api, type SessionStatus, type SignedInUser } from "@/lib/api"
import { instantSyncBlock, instantSyncHelpUrl } from "@/lib/instant-sync"

/**
 * Whether the User's rules run soon after their provider reports a change (Instant Sync), beside
 * incident emails. Where it cannot run for them, the row offers no switch: like incident emails
 * without email, it says why and links to the section of the Instant Sync guide that explains the
 * fix.
 */
export function InstantSyncItem({ user, onDone }: { user: SignedInUser; onDone: (message: string) => void }) {
  const block = instantSyncBlock(user.instant_sync_availability)
  return block ? (
    <InstantSyncUnavailable block={block} help={instantSyncHelpUrl(user.instant_sync_help)} />
  ) : (
    <InstantSyncChoice user={user} onDone={onDone} />
  )
}

type Block = NonNullable<ReturnType<typeof instantSyncBlock>>

function InstantSyncUnavailable({ block, help }: { block: Block; help: string | null }) {
  const { t } = useI18n()
  return (
    <div className="setting-item">
      <div className="setting-row">
        <div className="setting-copy">
          <h3>{t("settings.ownAccount.instantSync.title")}</h3>
          <p>{t("settings.ownAccount.instantSync.body")}</p>
          <p id="own-instant-sync-reason" className="setting-state">
            {t(`settings.ownAccount.instantSync.blocked.${block}`)}
          </p>
        </div>
        {help && <LearnWhyLink href={help} describedBy="own-instant-sync-reason" />}
      </div>
    </div>
  )
}

function InstantSyncChoice({ user, onDone }: { user: SignedInUser; onDone: (message: string) => void }) {
  const i18n = useI18n()
  const { t } = i18n
  const change = useInstantSyncChange(onDone)
  const checked = change.isPending ? change.variables : user.instant_sync
  return (
    <div className="setting-item">
      <div className="setting-row">
        <div className="setting-copy">
          <h3>{t("settings.ownAccount.instantSync.title")}</h3>
          <p>{t("settings.ownAccount.instantSync.body")}</p>
        </div>
        <label className="checkbox-row instant-sync-toggle" htmlFor="own-instant-sync">
          <input
            id="own-instant-sync"
            type="checkbox"
            checked={checked}
            disabled={change.isPending}
            onChange={(event) => change.mutate(event.target.checked)}
          />
          <span>
            <strong>{t("settings.ownAccount.instantSync.label")}</strong>
          </span>
        </label>
      </div>
      {change.error && (
        <p className="field-error" role="alert">
          {apiErrorMessage(i18n, change.error)}
        </p>
      )}
    </div>
  )
}

/**
 * Changes the choice. The switch shows the requested value only while the change is pending; then
 * it shows the session's, which the change's answer updates at once and every later refetch keeps
 * current, such as after another tab changed it.
 */
function useInstantSyncChange(onDone: (message: string) => void) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (wanted: boolean) => api.setInstantSync(wanted),
    onSuccess: async (changed) => {
      onDone(changed.instant_sync ? t("settings.ownAccount.instantSync.on") : t("settings.ownAccount.instantSync.off"))
      queryClient.setQueryData<SessionStatus>(["session"], (session) => session && { ...session, user: changed })
      await queryClient.invalidateQueries({ queryKey: ["session"] })
    },
  })
}
