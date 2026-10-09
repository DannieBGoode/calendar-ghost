import { useQuery } from "@tanstack/react-query"

import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { UserOverviewDetails } from "@/features/user-overview"
import { useI18n } from "@/i18n/provider"
import { api } from "@/lib/api"
import { useOverviewSharing } from "@/lib/use-people-access"

/**
 * What the Operator Overview shows Installation Administrators about the signed-in User, from
 * the same answer they read. Under Only me nobody else is here, so it is not shown.
 */
export function AdministratorViewSection() {
  const sharing = useOverviewSharing()
  if (sharing !== "shared") return null
  return <AdministratorView />
}

function AdministratorView() {
  const { t } = useI18n()
  const overview = useQuery({ queryKey: ["own-overview"], queryFn: api.ownOverview })
  return (
    <section className="settings-section" aria-labelledby="administrator-view-title">
      <div className="section-heading">
        <div>
          <h2 id="administrator-view-title">{t("settings.administratorView.title")}</h2>
          <p>{t("settings.administratorView.intro")}</p>
        </div>
      </div>
      {overview.isPending && <Skeleton className="h-16 w-full" />}
      {overview.error && (
        <div className="inline-error integration-load-error" role="alert">
          <span>{t("settings.administratorView.loadFailure")}</span>
          <Button type="button" variant="outline" onClick={() => void overview.refetch()}>
            {t("settings.administratorView.tryAgain")}
          </Button>
        </div>
      )}
      {overview.data && <UserOverviewDetails overview={overview.data} headingLevel={3} />}
    </section>
  )
}
