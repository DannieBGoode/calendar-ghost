import { useI18n } from "@/i18n/provider"
import type { MessageKey } from "@/i18n/types"
import {
  SETTINGS_TABS,
  appPathForSettingsTab,
  isPlainLeftClick,
  type OpenSettingsTab,
  type SettingsTab,
} from "@/lib/navigation"
import { cn } from "@/lib/utils"

const TAB_LABELS: Record<SettingsTab, MessageKey> = {
  connections: "settings.tabs.connections",
  account: "settings.tabs.account",
  installation: "settings.tabs.installation",
}

/**
 * Links to each Settings tab. Each has its own address, so they are navigation rather than an
 * ARIA tablist; a plain click opens the tab in place, and any other click is left to the browser.
 */
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
  const tabs = SETTINGS_TABS.filter((tab) => administrator || tab !== "installation")
  return (
    <nav className="settings-tabs" aria-label={t("settings.tabs.label")}>
      {tabs.map((tab) => (
        <a
          key={tab}
          href={appPathForSettingsTab(tab)}
          className={cn("settings-tab", tab === current && "active")}
          aria-current={tab === current ? "page" : undefined}
          onClick={(event) => {
            if (!isPlainLeftClick(event)) return
            event.preventDefault()
            onOpen(tab)
          }}
        >
          {t(TAB_LABELS[tab])}
        </a>
      ))}
    </nav>
  )
}
