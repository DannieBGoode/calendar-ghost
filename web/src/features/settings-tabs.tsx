import { PageTabs } from "@/components/page-tabs"
import { useI18n } from "@/i18n/provider"
import type { MessageKey } from "@/i18n/types"
import { SETTINGS_TABS, appPathForSettingsTab, type OpenSettingsTab, type SettingsTab } from "@/lib/navigation"

const TAB_LABELS: Record<SettingsTab, MessageKey> = {
  account: "settings.tabs.account",
  connections: "settings.tabs.connections",
  administration: "settings.tabs.administration",
}

/** Links to each Settings tab; Administration is offered to Installation Administrators only. */
export function SettingsTabs({
  current,
  administrator,
  onOpen,
}: {
  current: SettingsTab
  administrator: boolean
  onOpen: OpenSettingsTab
}) {
  const { t } = useI18n()
  const tabs = SETTINGS_TABS.filter((tab) => administrator || tab !== "administration").map((tab) => ({
    id: tab,
    label: t(TAB_LABELS[tab]),
    href: appPathForSettingsTab(tab),
  }))
  return <PageTabs label={t("settings.tabs.label")} tabs={tabs} current={current} onOpen={onOpen} />
}
