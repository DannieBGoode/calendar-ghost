import { useQuery } from "@tanstack/react-query"
import { UserPlus } from "lucide-react"
import { useEffect, useState } from "react"

import { PageTabs } from "@/components/page-tabs"
import { PageSkeleton } from "@/components/page-skeleton"
import { Button } from "@/components/ui/button"
import { InvitationsSection } from "@/features/people-invitations"
import { PlansSection } from "@/features/people-plans"
import { PeopleRoster } from "@/features/people-roster"
import { useI18n } from "@/i18n/provider"
import type { MessageKey } from "@/i18n/types"
import { api } from "@/lib/api"
import { documentTitle } from "@/lib/brand"
import { appPathForPeopleTab, type OpenPerson, type PeopleTab } from "@/lib/navigation"
import { DEFAULT_PEOPLE_QUERY, peopleSearch } from "@/lib/people-query"
import { useNow } from "@/lib/use-now"
import { usePeopleAccess } from "@/lib/use-people-access"
import { useInvitations, type InvitationCommands } from "@/lib/use-invitations"
import { usePeopleLocation } from "@/lib/use-people-location"

/** What the browser tab says on each of People's tabs, before the product name. */
const TAB_TITLES: Record<PeopleTab, MessageKey> = {
  everyone: "people.page.title",
  invitations: "people.tabs.documentTitle.invitations",
  plans: "people.tabs.documentTitle.plans",
}

/**
 * The people who use this installation, for an Installation Administrator: who they are, their
 * role and state, when they last signed in, and whether their synchronization works, never what
 * they own. People comes first, with Installation Health above them; the invitations still
 * waiting, and the Plans that limit people, have tabs of their own. The app offers this page only
 * while the Registration Policy lets people join. `notice` says what just happened elsewhere, such
 * as deleting someone from their own page.
 */
export function PeopleView({
  tab,
  notice,
  onOpenPerson,
}: {
  tab: PeopleTab
  notice: string | null
  onOpenPerson: OpenPerson
}) {
  const { t } = useI18n()
  const access = usePeopleAccess()
  const session = useQuery({ queryKey: ["session"], queryFn: api.session })
  const user = session.data?.user
  if (access !== "open" || !user) return <PageSkeleton label={t("people.page.loading")} />
  return <PeopleContent initialTab={tab} currentUserId={user.id} notice={notice} onOpenPerson={onOpenPerson} />
}

function PeopleContent({
  initialTab,
  currentUserId,
  notice,
  onOpenPerson,
}: {
  initialTab: PeopleTab
  currentUserId: string
  notice: string | null
  onOpenPerson: OpenPerson
}) {
  const i18n = useI18n()
  const { t } = i18n
  const [tab, setTab] = useState(initialTab)
  const [query, update] = usePeopleLocation()
  const invitations = useInvitations()
  const now = useNow()
  // Counts arrivals at the list from elsewhere on this page, each of which starts at its heading.
  const [listArrivals, setListArrivals] = useState(0)
  useEffect(() => {
    document.title = documentTitle(i18n, i18n.t(TAB_TITLES[tab]))
  }, [i18n, tab])
  useEffect(() => {
    if (listArrivals > 0) document.getElementById("people-list-title")?.focus()
  }, [listArrivals])

  // Each tab has its own address; switching keeps this page, and what it shows, in place.
  function openTab(next: PeopleTab) {
    if (next === tab) return
    const search = next === "everyone" ? peopleSearch(query) : ""
    window.history.pushState(null, "", `${appPathForPeopleTab(next)}${search}`)
    setTab(next)
  }

  // Everyone who has a Plan, from its Remove note: that Plan alone filters the list, from its heading.
  function showHolders(plan: string) {
    const shown = { ...DEFAULT_PEOPLE_QUERY, plan }
    window.history.pushState(null, "", `${appPathForPeopleTab("everyone")}${peopleSearch(shown)}`)
    update(shown, "replace")
    setTab("everyone")
    setListArrivals((count) => count + 1)
  }

  function inviteSomeone() {
    openTab("invitations")
    invitations.invite.mutate()
  }

  return (
    <div className="page-section people-page">
      <div className="page-heading-row">
        <div>
          <h1>{t("people.page.title")}</h1>
          <p className="page-intro">{t("people.page.intro")}</p>
        </div>
        <div className="heading-action">
          <Button id="invite-someone" type="button" disabled={invitations.invite.isPending} onClick={inviteSomeone}>
            <UserPlus aria-hidden="true" />
            {invitations.invite.isPending ? t("people.invitations.inviting") : t("people.invitations.invite")}
          </Button>
        </div>
      </div>
      <PeopleTabs current={tab} invitations={invitations} onOpen={openTab} />
      {tab === "everyone" && (
        <PeopleRoster
          query={query}
          update={update}
          currentUserId={currentUserId}
          now={now}
          notice={notice}
          onOpenPerson={onOpenPerson}
        />
      )}
      {tab === "invitations" && <InvitationsSection commands={invitations} now={now} />}
      {tab === "plans" && <PlansSection onShowHolders={showHolders} />}
      <p className="sr-only" role="status">
        {invitations.message}
      </p>
    </div>
  )
}

function PeopleTabs({
  current,
  invitations,
  onOpen,
}: {
  current: PeopleTab
  invitations: InvitationCommands
  onOpen: (tab: PeopleTab) => void
}) {
  const { t } = useI18n()
  const waiting = invitations.invitations.data?.length ?? 0
  return (
    <PageTabs
      label={t("people.tabs.label")}
      current={current}
      onOpen={onOpen}
      tabs={[
        { id: "everyone", label: t("people.tabs.everyone"), href: appPathForPeopleTab("everyone") },
        {
          id: "invitations",
          label: t("people.tabs.invitations"),
          href: appPathForPeopleTab("invitations"),
          count: waiting,
          countLabel: t("people.tabs.waiting", { count: waiting }),
        },
        { id: "plans", label: t("people.tabs.plans"), href: appPathForPeopleTab("plans") },
      ]}
    />
  )
}
