import { Moon, Sun } from "lucide-react"

import { useTheme } from "@/components/theme-provider"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/i18n/provider"

type ThemeToggleProps = {
  className?: string
}

export function ThemeToggle({ className }: ThemeToggleProps) {
  const { t } = useI18n()
  const { resolvedTheme, setPreference } = useTheme()
  const darkModeEnabled = resolvedTheme === "dark"
  const title = darkModeEnabled ? t("common.themeToggle.switchToLight") : t("common.themeToggle.switchToDark")

  return (
    <Button
      type="button"
      className={className}
      variant="ghost"
      size="icon"
      aria-label={t("common.themeToggle.label")}
      aria-pressed={darkModeEnabled}
      title={title}
      onClick={() => setPreference(darkModeEnabled ? "light" : "dark")}
    >
      {darkModeEnabled ? <Sun aria-hidden="true" /> : <Moon aria-hidden="true" />}
    </Button>
  )
}
