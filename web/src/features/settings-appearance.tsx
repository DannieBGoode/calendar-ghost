import { NativeSelect } from "@/components/ui/native-select"
import { useTheme } from "@/components/theme-provider"
import { useI18n } from "@/i18n/provider"
import type { DarkPalette, ThemePreference } from "@/lib/theme"

/** Theme and dark palette, saved in this browser only. */
export function AppearanceSection() {
  const { t } = useI18n()
  const { preference, setPreference, darkPalette, setDarkPalette } = useTheme()
  return (
    <section className="settings-section" aria-labelledby="appearance-title">
      <div className="section-heading">
        <div>
          <h2 id="appearance-title">{t("settings.appearance.title")}</h2>
          <p>{t("settings.appearance.intro")}</p>
        </div>
      </div>
      <div className="settings-list">
        <div className="setting-row">
          <div>
            <h3 id="theme-title">{t("settings.appearance.theme.title")}</h3>
            <p>{t("settings.appearance.theme.body")}</p>
          </div>
          <div className="appearance-control">
            <NativeSelect
              id="theme-preference"
              aria-labelledby="theme-title"
              value={preference}
              onChange={(event) => setPreference(event.target.value as ThemePreference)}
            >
              <option value="system">{t("settings.appearance.theme.system")}</option>
              <option value="light">{t("settings.appearance.theme.light")}</option>
              <option value="dark">{t("settings.appearance.theme.dark")}</option>
            </NativeSelect>
          </div>
        </div>
        <div className="setting-row">
          <div>
            <h3 id="dark-palette-title">{t("settings.appearance.darkPalette.title")}</h3>
            <p>{t("settings.appearance.darkPalette.body")}</p>
          </div>
          <div className="appearance-control">
            <NativeSelect
              id="dark-palette"
              aria-labelledby="dark-palette-title"
              value={darkPalette}
              onChange={(event) => setDarkPalette(event.target.value as DarkPalette)}
            >
              <option value="twilight">{t("settings.appearance.darkPalette.twilight")}</option>
              <option value="midnight">{t("settings.appearance.darkPalette.midnight")}</option>
            </NativeSelect>
          </div>
        </div>
      </div>
    </section>
  )
}
