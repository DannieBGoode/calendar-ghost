import { useMutation, useQueryClient } from "@tanstack/react-query"

import { LearnWhyLink } from "@/components/learn-why-link"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import { api, type SignedInUser } from "@/lib/api"
import { instantSyncBlock, instantSyncHelpUrl } from "@/lib/instant-sync"

/**
 * Whether the User's rules run soon after their provider reports a change (Instant Sync), beside
 * incident emails. Where it cannot run for them, the switch is disabled, says why, and links to
 * the section of the Instant Sync guide that explains the fix.
 */
export function InstantSyncItem({ user, onDone }: { user: SignedInUser; onDone: (message: string) => void }) {
  const i18n = useI18n()
  const { t } = i18n
  const { change, shown } = useInstantSyncChoice(user, onDone)
  const block = instantSyncBlock(shown.instant_sync_availability)
  const help = block ? instantSyncHelpUrl(shown.instant_sync_help) : null
  const checked = change.isPending ? change.variables : shown.instant_sync
  return (
    <div className="setting-item">
      <div className="setting-row">
        <div>
          <h3>{t("settings.ownAccount.instantSync.title")}</h3>
          <p>{t("settings.ownAccount.instantSync.body")}</p>
          {block && (
            <p id="own-instant-sync-reason">
              {t(`settings.ownAccount.instantSync.blocked.${block}`)}{" "}
              {help && <LearnWhyLink href={help} />}
            </p>
          )}
        </div>
        <label className="checkbox-row instant-sync-toggle" htmlFor="own-instant-sync">
          <input
            id="own-instant-sync"
            type="checkbox"
            checked={block === null && checked}
            disabled={block !== null || change.isPending}
            aria-describedby={block ? "own-instant-sync-reason" : undefined}
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

/** The choice as the last change answered it, or as the session says, and the change itself. */
function useInstantSyncChoice(user: SignedInUser, onDone: (message: string) => void) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const change = useMutation({
    mutationFn: (wanted: boolean) => api.setInstantSync(wanted),
    onSuccess: async (changed) => {
      onDone(changed.instant_sync ? t("settings.ownAccount.instantSync.on") : t("settings.ownAccount.instantSync.off"))
      await queryClient.invalidateQueries({ queryKey: ["session"] })
    },
  })
  return { change, shown: change.data ?? user }
}
