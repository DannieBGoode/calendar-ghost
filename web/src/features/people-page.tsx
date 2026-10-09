import { useQuery } from "@tanstack/react-query"
import { UserPlus } from "lucide-react"
import { useState } from "react"

import { PageTabs } from "@/components/page-tabs"
import { PageSkeleton } from "@/components/page-skeleton"
import { Button } from "@/components/ui/button"
import { InvitationsSection } from "@/features/people-invitations"
import { PeopleRoster } from "@/features/people-roster"
import { useI18n } from "@/i18n/provider"
import { api } from "@/lib/api"
import { appPathForPeopleTab, type OpenPerson, type PeopleTab } from "@/lib/navigation"
import { peopleSearch } from "@/lib/people-query"
import { useNow } from "@/lib/use-now"
import { usePeopleAccess } from "@/lib/use-people-access"
import { useInvitations, type InvitationCommands } from "@/lib/use-invitations"
import { usePeopleLocation } from "@/lib/use-people-location"

/**
 * The people who use this installation, for an Installation Administrator: who they are, their
 * role and state, when they last signed in, and whether their synchronization works, never what
 * they own. People comes first, with Installation Health above them; the invitations still
 * waiting have a tab of their own. The app offers this page only while the Registration Policy
 * lets people join. `notice` says what just happened elsewhere, such as deleting someone from
 * their own page.
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
  const { t } = useI18n()
  const [tab, setTab] = useState(initialTab)
  const [query, update] = usePeopleLocation()
  const invitations = useInvitations()
  const now = useNow()

  // Each tab has its own address; switching keeps this page, and what it shows, in place.
  function openTab(next: PeopleTab) {
    if (next === tab) return
    const search = next === "everyone" ? peopleSearch(query) : ""
    window.history.pushState(null, "", `${appPathForPeopleTab(next)}${search}`)
    setTab(next)
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
      {tab === "everyone" ? (
        <PeopleRoster
          query={query}
          update={update}
          currentUserId={currentUserId}
          now={now}
          notice={notice}
          onOpenPerson={onOpenPerson}
        />
      ) : (
        <InvitationsSection commands={invitations} now={now} />
      )}
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
      ]}
    />
  )
}
